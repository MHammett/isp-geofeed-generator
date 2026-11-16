// Load the untouched pinned ESM source with Node 24. No Babel/release tooling needed.
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL, fileURLToPath} = require('node:url');
const {registerHooks} = require('node:module');
const source = pathToFileURL(path.resolve(process.argv[2], 'src') + path.sep).href;
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (context.parentURL?.startsWith(source) && specifier.startsWith('.') && !path.extname(specifier)) {
      specifier += '.js';
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.startsWith(source) && (url.endsWith('.js') || url.endsWith('.json'))) {
      const data = fs.readFileSync(fileURLToPath(url), 'utf8');
      return {format:'module',source:url.endsWith('.json') ? 'export default '+data+';' : data,shortCircuit:true};
    }
    return nextLoad(url, context);
  }
});
import(source+'validator.js').then(({default: validator}) => {
  const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
  console.log(JSON.stringify(cases.map(item => ({name:item.name,
    errors:item.csv.split(/\r?\n/).filter(Boolean).flatMap(line => validator.fromLine(line) || [])}))));
}).catch(error => { console.error(error); process.exitCode=1; });
