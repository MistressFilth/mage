from mage.verification.host_overrides import HostConfig


def test_host_config_has_max_concurrent_llm_calls():
    cfg = HostConfig()
    assert cfg.max_concurrent_llm_calls == 7


def test_host_config_max_concurrent_llm_calls_overridable():
    cfg = HostConfig(max_concurrent_llm_calls=2)
    assert cfg.max_concurrent_llm_calls == 2