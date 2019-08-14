#!/usr/bin/python

# Copyright: (c) 2019, Benjamin Bertrand <beenje@gmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

ANSIBLE_METADATA = {
    "metadata_version": "1.1",
    "status": ["preview"],
    "supported_by": "community",
}

DOCUMENTATION = """
---
module: conda

short_description: Manages I(conda) packages

version_added: "2.9"

description:
    - Install, update, remove packages with the I(conda) package manager.
    - This module requires conda to be already installed.
    - The minimum conda version required is 4.6.

options:
    name:
        description:
            - A package name or package specification, like C(name=1.0).
            - The package specification is only accepted with state=present.
            - For state=latest or state=absent, use package name only.
            - Accept a list of packages as well.
        required: true
        type: list
    state:
        description:
            - Wether to install (C(present)), update (C(latest)) or remove (C(absent)) packages
            - C(present) will ensure that the given packages are installed
            - C(latest) will update the given packages to the latest available version
            - C(absent) will remove the specified packages
            - If the environment doesn't exist, it will be created.
        choices: [ absent, latest, present ]
        default: present
        type: str
    environment:
        description:
            - Environment name or full path.
            - For example C(python3) or C(/opt/conda/envs/python3).
        default: base
        type: str
    executable:
        description:
            - Full path of the conda command to use, like C(/home/conda/bin/conda).
            - If not specified, C(conda) will be searched in the PATH as well as
              the /opt/conda/bin directory.
        type: path
    channels:
        description:
            - List of extra channels to use when installing packages.
        type: list

requirements:
  - conda >= 4.6

author:
    - Benjamin Bertrand (@beenje)
"""

EXAMPLES = """
- name: install flask 1.0 and Python 3.7
  conda:
    name:
      - python=3.7
      - flask=1.0
    state: present
    environment: myapp

- name: install flask from conda-forge
  conda:
    name: flask
    state: present
    environment: flaskapp
    channels:
      - conda-forge

- name: update flask to the latest version
  conda:
    name: flask
    state: latest
    environment: myapp

- name: update conda to the latest version
  conda:
    name: conda
    state: latest

- name: remove flask from myapp environment
  conda:
    name: flask
    state: absent
    environment: myapp
"""

RETURN = """
cmd:
    description: The conda command that was run
    type: list
    returned: always
rc:
    description: The return code of the command
    type: int
    returned: always
stdout_json:
    description: The json output of the command
    type: dict
    returned: always
stderr:
    description: The standard error of the command
    type: str
    returned: always
"""

import json
import os
from collections import namedtuple
from ansible.module_utils.basic import AnsibleModule

Result = namedtuple("Result", "changed cmd rc stdout_json stderr")


class Conda:
    """Class to perform conda operations"""

    def __init__(self, module):
        self.module = module
        self.executable = module.params["executable"] or module.get_bin_path(
            "conda", required=True, opt_dirs=["/opt/conda/bin"]
        )
        self.environment = module.params["environment"]
        if os.path.sep in self.environment:
            env_flag = "--prefix"
        else:
            env_flag = "--name"
        self.env_args = [env_flag, self.environment]
        self.default_args = ["-y"] + self.env_args
        for channel in module.params["channels"]:
            self.default_args.extend(["--channel", channel])
        if module.check_mode:
            self.default_args.append("--dry-run")

    @staticmethod
    def changed(stdout_json):
        """Return True if any change was performed by the conda command"""
        # When conda didn't install/update anything, the output is:
        # {
        #  "message": "All requested packages already installed.",
        #  "success": true
        # }
        # When conda has some operations to perform, the list of actions
        # is returned in the json output:
        # {
        #  "actions": {
        #   "FETCH": [],
        #   "LINK": [
        #    {
        #     "base_url": "https://repo.anaconda.com/pkgs/main",
        #     "build_number": 0,
        #     "build_string": "py_0",
        #     "channel": "pkgs/main",
        #     "dist_name": "flask-1.1.1-py_0",
        #     "name": "flask",
        #     "platform": "noarch",
        #     "version": "1.1.1"
        #    }
        #   ],
        #   "PREFIX": "/opt/conda/envs/python3"
        #  },
        #  "prefix": "/opt/conda/envs/python3",
        #  "success": true
        # }
        if "actions" not in stdout_json:
            return False
        return True

    def run_conda(self, cmd, *args, **kwargs):
        """Run a conda commmand"""
        fail_on_error = kwargs.pop("fail_on_error", True)
        add_default_args = kwargs.pop("add_default_args", True)
        cmd = [self.executable, cmd] + ["--quiet", "--json"]
        if add_default_args:
            cmd.extend(self.default_args)
        cmd.extend(args)
        rc, stdout, stderr = self.module.run_command(cmd)
        if fail_on_error and rc != 0:
            self.module.fail_json(
                command=cmd, msg="Command failed", rc=rc, stdout=stdout, stderr=stderr
            )
        try:
            stdout_json = json.loads(stdout)
        except ValueError:
            self.module.fail_json(
                command=cmd,
                msg="Failed to parse the output of the command",
                stdout=stdout,
                stderr=stderr,
            )
        return Result(self.changed(stdout_json), cmd, rc, stdout_json, stderr)

    def list_packages(self):
        """Return the list of packages name installed in the environment"""
        result = self.run_conda("list", *self.env_args, add_default_args=False)
        return [pkg["name"] for pkg in result.stdout_json]

    def env_exists(self):
        """Return True if the environment exists

        The existence is checked by running the conda list -n/-p environment command.
        """
        result = self.run_conda(
            "list", *self.env_args, add_default_args=False, fail_on_error=False
        )
        return result.rc == 0

    def install(self, packages):
        """Install the given conda packages"""
        return self.run_conda("install", "-S", *packages)

    def update(self, packages):
        """Update the given conda packages"""
        return self.run_conda("update", *packages)

    def create(self, packages):
        """Create a new environment with the given conda packages"""
        return self.run_conda("create", *packages)

    def remove(self, packages):
        """Remove the conda packages from the environment"""
        installed_packages = self.list_packages()
        # clean the packages name by removing the version spec
        # to keep only the package name in lowercase
        packages_names = [pkg.split("=")[0].lower() for pkg in packages]
        packages_to_remove = set(installed_packages) & set(packages_names)
        if packages_to_remove:
            return self.run_conda("remove", *packages_to_remove)
        else:
            # None of the given packages are in the environment
            # Nothing to do
            return Result(False, "", 0, {}, "")


def run_module():
    module_args = dict(
        name=dict(type="list", required=True),
        state=dict(choices=["present", "absent", "latest"], default="present"),
        executable=dict(type="path"),
        environment=dict(type="str", default="base"),
        channels=dict(type="list", default=[]),
    )

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)
    state = module.params["state"]
    packages = module.params["name"]

    conda = Conda(module)

    if state == "present":
        if conda.env_exists():
            result = conda.install(packages)
        else:
            result = conda.create(packages)
    elif state == "latest":
        if conda.env_exists():
            result = conda.update(packages)
        else:
            result = conda.create(packages)
    elif state == "absent":
        result = conda.remove(packages)

    module.exit_json(**result._asdict())


def main():
    run_module()


if __name__ == "__main__":
    main()
