"""yamlスタブ: WASMビルドではシナリオYAMLを読まない(介入は直接構築)。
import自体は interventions/presets が行うので、モジュールとして存在すれば良い。"""


def safe_load(_s):
    raise RuntimeError("yaml is not available in the WASM build")
