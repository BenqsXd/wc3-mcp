from wc3mcp import config


def test_home_uses_the_real_folder_of_a_packaged_python(tmp_path, monkeypatch):
    monkeypatch.delenv("WC3MCP_HOME")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(config, "package_family", lambda: "PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0")
    assert config.home() == tmp_path / "Packages" / "PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0" / "LocalCache" \
        / "Local" / "wc3mcp"
    monkeypatch.setattr(config, "package_family", lambda: None)
    assert config.home() == tmp_path / "wc3mcp"


def test_package_family_answers_without_failing():
    assert config.package_family() is None or "_" in config.package_family()
