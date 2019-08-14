import pytest
from units.compat.mock import MagicMock
from ansible.modules.packaging.os.conda import Conda


PACKAGES_ALREADY_INSTALLED_STDOUT = {
    "message": "All requested packages already installed.",
    "success": True,
}
CONDA_ACTIONS_STDOUT = {
    "actions": {
        "FETCH": [],
        "LINK": [
            {
                "base_url": "https://repo.anaconda.com/pkgs/main",
                "build_number": 0,
                "build_string": "py_0",
                "channel": "pkgs/main",
                "dist_name": "flask-1.1.1-py_0",
                "name": "flask",
                "platform": "noarch",
                "version": "1.1.1",
            }
        ],
        "PREFIX": "/opt/conda/envs/python3",
    },
    "prefix": "/opt/conda/envs/python3",
    "success": True,
}


class FakeModule:
    """Class to mock mock AnsibleModule"""

    def __init__(
        self,
        environment="myenv",
        executable="/mypath/conda",
        channels=None,
        check_mode=False,
    ):
        self.params = {
            "environment": environment,
            "executable": executable,
            "channels": channels or [],
        }
        self.check_mode = check_mode
        self.run_command = MagicMock()


@pytest.fixture
def conda_default():
    """Return a Conda instance with default parameters"""
    module = FakeModule()
    module.run_command.return_value = 0, "{}", ""
    return Conda(module)


@pytest.mark.parametrize(
    "stdout_json, expected",
    (
        (PACKAGES_ALREADY_INSTALLED_STDOUT, False),
        ({}, False),
        ({"success": True}, False),
        (CONDA_ACTIONS_STDOUT, True),
        ({"actions": {}}, True),
    ),
)
def test_conda_command_changed(stdout_json, expected):
    # Test if a change was performed based on the json output of the conda command
    assert Conda.changed(stdout_json) is expected


@pytest.mark.parametrize(
    "name, option",
    (("myenv", "--name"), ("./myenv", "--prefix"), ("/opt/conda/envs/foo", "--prefix")),
)
def test_conda_env_args(name, option):
    # Test that the proper option --name or --prefix is used
    # depending if a path or name is passed
    module = FakeModule(environment=name)
    conda = Conda(module)
    assert conda.env_args == [option, name]


@pytest.mark.parametrize("rc, expected", ((0, True), (1, False), (127, False)))
def test_conda_env_exists(rc, expected):
    # env_exists should return True if the conda --list command returns without error
    module = FakeModule()
    module.run_command.return_value = rc, "{}", ""
    conda = Conda(module)
    result = conda.env_exists()
    assert module.run_command.called_once_with("conda --list --name myenv")
    assert result is expected


def test_conda_list_packages():
    module = FakeModule()
    stdout = """[
        {
            "base_url": "https://conda.anaconda.org/conda-forge",
            "build_number": 0,
            "build_string": "py36_0",
            "channel": "conda-forge",
            "dist_name": "click-6.7-py36_0",
            "name": "click",
            "platform": "osx-64",
            "version": "6.7"
        },
        {
            "base_url": "https://conda.anaconda.org/conda-forge",
            "build_number": 0,
            "build_string": "py36_0",
            "channel": "conda-forge",
            "dist_name": "cookiecutter-1.5.1-py36_0",
            "name": "cookiecutter",
            "platform": "osx-64",
            "version": "1.5.1"
        }
    ]"""
    module.run_command.return_value = 0, stdout, ""
    conda = Conda(module)
    result = conda.list_packages()
    assert module.run_command.called_once_with("conda --list --name myenv")
    assert result == ["click", "cookiecutter"]


def test_conda_no_packages_to_remove(conda_default):
    # Nothing should be done in the packages given are not in
    # the environment
    conda_default.list_packages = MagicMock()
    conda_default.list_packages.return_value = ["flask", "bar"]
    result = conda_default.remove(["foo", "Python"])
    assert result.cmd == ""
    assert not result.changed
    assert not conda_default.module.run_command.called


def test_conda_remove_command_options(conda_default):
    conda_default.list_packages = MagicMock()
    conda_default.list_packages.return_value = ["python", "bar"]
    result = conda_default.remove(["foo", "Python"])
    assert conda_default.module.run_command.called
    assert result.cmd == [
        "/mypath/conda",
        "remove",
        "--quiet",
        "--json",
        "-y",
        "--name",
        "myenv",
        "python",
    ]


def test_conda_install_command_options(conda_default):
    result = conda_default.install(["foo=1.0", "bar"])
    assert result.cmd == [
        "/mypath/conda",
        "install",
        "--quiet",
        "--json",
        "-y",
        "--name",
        "myenv",
        "-S",
        "foo=1.0",
        "bar",
    ]


def test_conda_update_command_options(conda_default):
    result = conda_default.update(["foo=1.0", "bar"])
    assert result.cmd == [
        "/mypath/conda",
        "update",
        "--quiet",
        "--json",
        "-y",
        "--name",
        "myenv",
        "foo=1.0",
        "bar",
    ]


def test_conda_create_command_options(conda_default):
    result = conda_default.create(["foo=1.0", "bar"])
    assert result.cmd == [
        "/mypath/conda",
        "create",
        "--quiet",
        "--json",
        "-y",
        "--name",
        "myenv",
        "foo=1.0",
        "bar",
    ]


@pytest.mark.parametrize("cmd", ("install", "update", "create", "remove"))
def test_conda_dry_run_command(cmd):
    module = FakeModule(check_mode=True)
    module.run_command.return_value = 0, "{}", ""
    conda = Conda(module)
    conda.list_packages = MagicMock()
    conda.list_packages.return_value = ["bar"]
    result = getattr(conda, cmd)(["foo", "bar"])
    assert "--dry-run" in result.cmd
