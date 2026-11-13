import vv_backend


def test_package_imports() -> None:
    assert vv_backend.__version__ == "0.1.0"
