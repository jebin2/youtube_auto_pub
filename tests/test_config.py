from youtube_auto_pub.config import YouTubeConfig, DEFAULT_SCOPES


def test_zero_arg_config_reads_env(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_env")
    monkeypatch.setenv("HF_YT_CRED_REPO_ID", "me/repo")
    monkeypatch.setenv("ENCRYPT_KEY", "env-key")

    config = YouTubeConfig()

    assert config.hf_token == "hf_env"
    assert config.hf_repo_id == "me/repo"
    assert config.encryption_key == "env-key"


def test_hf_repo_id_falls_back_to_generic_env(monkeypatch):
    monkeypatch.setenv("HF_REPO_ID", "generic/repo")
    assert YouTubeConfig().hf_repo_id == "generic/repo"


def test_explicit_args_override_env(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_env")
    monkeypatch.setenv("HF_YT_CRED_REPO_ID", "me/repo")
    monkeypatch.setenv("ENCRYPT_KEY", "env-key")

    config = YouTubeConfig(hf_repo_id="other/repo", encryption_key=b"explicit")

    assert config.hf_repo_id == "other/repo"
    assert config.encryption_key == b"explicit"
    assert config.hf_token == "hf_env"  # untouched fields still fall back


def test_defaults():
    config = YouTubeConfig()
    assert config.client_secret_filename == "ytcredentials.json"
    assert config.token_filename == "yttoken.json"
    assert config.hf_repo_id is None  # no baked-in personal defaults
    assert config.scopes == DEFAULT_SCOPES
    assert config.scopes is not DEFAULT_SCOPES  # per-instance copy


def test_paths_join_encrypt_path():
    config = YouTubeConfig(encrypt_path="/data/creds",
                           client_secret_filename="c.json",
                           token_filename="t.json")
    assert config.client_id_path == "/data/creds/c.json"
    assert config.token_file_path == "/data/creds/t.json"
