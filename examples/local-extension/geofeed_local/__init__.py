"""Copy this package to a separate repository before making local changes."""
import json
from pathlib import Path
from isp_geofeed_generator.sdk import GeofeedError, SourceAdapter, TargetAdapter, TARGET_API_VERSION, REJECT, publish_file


class JsonSource:
    def __init__(self, path):
        self.path = Path(path)

    def snapshot(self):
        with self.path.open('rb') as stream:
            data = stream.read(8_000_001)
        if len(data) > 8_000_000:
            raise GeofeedError('Local JSON input exceeds size limit')
        value = json.loads(data)
        return {**value, 'source': 'local_json', 'support_level': 'initial local extension'}

    def for_publication(self, snapshot):
        return snapshot


class LocalFile:
    def __init__(self, path):
        self.path = path

    def publish(self, csv, state_dir, **guards):
        # Delegate withdrawal checks, atomic writes and read-back to the SDK.
        return publish_file(self.path, csv, state_dir, **guards)


SOURCE = SourceAdapter(lambda settings, credentials: JsonSource(settings['input_path']),
                       settings=frozenset({'input_path'}))
TARGET = TargetAdapter(lambda settings, credentials: LocalFile(settings['path']),
                       settings=frozenset({'path'}))


class StrictFileV2(LocalFile):
    def publish(self, csv, state_dir, *, overlap_policy, **guards):
        if overlap_policy != REJECT:
            raise GeofeedError('This example supports strict output only')
        return super().publish(csv, state_dir, **guards)


# A new contract version does not itself mean a target supports nesting.
TARGET_V2 = TargetAdapter(lambda settings, credentials: StrictFileV2(settings['path']),
                          api_version=TARGET_API_VERSION, settings=frozenset({'path'}))
