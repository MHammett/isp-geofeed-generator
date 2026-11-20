"""Prove a bounded JSONPath subset stays in ignored root entity data. Never evaluate it."""
import re

from .client import GeofeedError

# The lexer finds token boundaries; _quoted enforces quote style and scalar rules.
_TOKEN = re.compile(r'''(?P<string>"(?:[^"\\\x00-\x1f]|\\(?:["'\\/bfnrt]|u[0-9a-fA-F]{4}))*"|'(?:[^'\\\x00-\x1f]|\\(?:["'\\/bfnrt]|u[0-9a-fA-F]{4}))*')|(?P<name>[A-Za-z_][A-Za-z0-9_]{0,63})|(?P<number>0|[1-9][0-9]{0,5})|(?P<equal>==)|(?P<symbol>[$@.\[\]()*?:])''')
MAX_REDACTIONS = 100
MAX_PATH = 2048
MAX_TOKENS = 256


def _quoted(value):
    """Check quoted-token scalars and escapes without decoding or evaluating it."""
    quote, position, end = value[0], 1, len(value) - 1
    while position < end:
        codepoint = ord(value[position])
        if 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError()
        if value[position] != '\\':
            position += 1
            continue
        position += 1
        escape = value[position]
        if escape == 'u':
            unit = int(value[position + 1:position + 5], 16)
            position += 5
            if 0xD800 <= unit <= 0xDBFF:
                if value[position:position + 2] != '\\u' or position + 6 > end:
                    raise ValueError()
                low = int(value[position + 2:position + 6], 16)
                if not 0xDC00 <= low <= 0xDFFF:
                    raise ValueError()
                position += 6
            elif 0xDC00 <= unit <= 0xDFFF:
                raise ValueError()
        else:
            if escape not in (quote, '\\', '/', 'b', 'f', 'n', 'r', 't'):
                raise ValueError()
            position += 1


class _Path:
    def __init__(self, value):
        if (not isinstance(value, str) or not 1 <= len(value) <= MAX_PATH
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError()
        tokens, offset = [], 0
        while offset < len(value):
            if value[offset] == ' ':
                offset += 1
                continue
            match = _TOKEN.match(value, offset)
            if match is None or len(tokens) >= MAX_TOKENS:
                raise ValueError()
            token = (match.lastgroup, match.group(), match.start(), match.end())
            if token[0] == 'string':
                if len(token[1]) > 256:
                    raise ValueError()
                _quoted(token[1])
            tokens.append(token)
            offset = match.end()
        self.tokens, self.position = tokens, 0

    def peek(self, value):
        return self.position < len(self.tokens) and self.tokens[self.position][1] == value

    def take(self, value):
        if not self.peek(value):
            raise ValueError()
        self.position += 1

    def atom(self, kind):
        if self.position >= len(self.tokens) or self.tokens[self.position][0] != kind:
            raise ValueError()
        value = self.tokens[self.position][1]
        self.position += 1
        return value

    def steps(self, *, singular=False):
        result = []
        while self.peek('.') or self.peek('['):
            result.append(self.step(singular=singular))
        return tuple(result)

    def step(self, *, singular=False):
        if self.peek('.'):
            self.take('.')
            if (self.position >= len(self.tokens)
                    or self.tokens[self.position][2] != self.tokens[self.position - 1][3]):
                raise ValueError()
            return ('member', self.atom('name'))
        self.take('[')
        if self.position < len(self.tokens) and self.tokens[self.position][0] == 'string':
            # Keep quoted names opaque. Escaped root aliases are unsupported;
            # quoted suffix keys are still single downward member selections.
            result = ('member', self.atom('string')[1:-1])
        elif self.peek('?') and not singular:
            self.take('?')
            parenthesized = self.peek('(')
            if parenthesized:
                self.take('(')
            self.take('@')
            relative = self.steps(singular=True)
            self.take('==')
            literal = self.atom('string')
            if parenthesized:
                self.take(')')
            result = ('filter', relative, literal)
        elif self.peek('*') and not singular:
            self.take('*')
            result = ('wildcard',)
        else:
            start = None if self.peek(':') else int(self.atom('number'))
            if self.peek(':') and not singular:
                self.take(':')
                end = None if self.peek(']') else int(self.atom('number'))
                result = ('slice', start, end)
            else:
                result = ('index', start)
        self.take(']')
        return result

    def entities(self):
        self.take('$')
        steps = self.steps()
        if self.position != len(self.tokens):
            raise ValueError()
        if not steps or steps[0] != ('member', 'entities'):
            raise ValueError()
        return steps


def contact_path(value):
    """Return syntax only, never matched values or executable expressions."""
    return _Path(value).entities()


def _label(value):
    # Validate only the standard shape. Human labels never select safe fields.
    return (isinstance(value, dict) and bool(value) and not set(value) - {'type', 'description'}
            and all(isinstance(text, str) and 1 <= len(text) <= 1024
                    and not any(ord(c) < 32 or ord(c) == 127 for c in text)
                    for text in value.values()))


def validate_redactions(source):
    if 'redacted' not in source:
        return 0
    try:
        declarations = source.get('rdapConformance')
        if not isinstance(declarations, list) or 'redacted' not in declarations:
            raise ValueError()
        rows = source['redacted']
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_REDACTIONS:
            raise ValueError()
        allowed = {'name', 'prePath', 'postPath', 'replacementPath', 'pathLang', 'method', 'reason'}
        for row in rows:
            if (not isinstance(row, dict) or set(row) - allowed or not _label(row.get('name'))
                    or ('reason' in row and not _label(row['reason']))
                    or row.get('pathLang', 'jsonpath') != 'jsonpath'):
                raise ValueError()
            method = row.get('method', 'removal')
            if method not in ('removal', 'emptyValue', 'partialValue', 'replacementValue'):
                raise ValueError()
            paths = [key for key in ('prePath', 'postPath', 'replacementPath') if key in row]
            if ('prePath' in row) == ('postPath' in row):
                raise ValueError()
            if method == 'removal' and paths != ['prePath']:
                raise ValueError()
            if method in ('emptyValue', 'partialValue') and paths != ['postPath']:
                raise ValueError()
            # Replacement in place uses postPath. If the original field is gone,
            # require the new location as well, even though RFC 9537 permits omission.
            if method == 'replacementValue' and 'prePath' in row and 'replacementPath' not in row:
                raise ValueError()
            for key in paths:
                contact_path(row[key])
        return len(rows)
    except (ValueError, TypeError, RecursionError):
        raise GeofeedError('Saved RDAP redaction is not supported by this reader: each declared path must use the supported JSONPath subset inside ignored root entities; preserve the original reply, no comparison made') from None
