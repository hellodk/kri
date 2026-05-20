#!/usr/bin/env python3
# playbooks/inventory/dynamic.py
"""
Minimal Ansible dynamic inventory for kri bootstrap runs.
Reads TARGET_HOST, ANSIBLE_USER, ANSIBLE_PASSWORD from environment.
"""
import json
import os
import sys

if "--list" in sys.argv:
    host = os.environ.get("TARGET_HOST", "")
    user = os.environ.get("ANSIBLE_USER", "admin")
    password = os.environ.get("ANSIBLE_PASSWORD", "")
    print(json.dumps({
        "target": {"hosts": [host]},
        "_meta": {
            "hostvars": {
                host: {
                    "ansible_host": host,
                    "ansible_user": user,
                    "ansible_ssh_pass": password,
                    "ansible_become_password": password,
                }
            }
        }
    }))
elif "--host" in sys.argv:
    print(json.dumps({}))
else:
    print(json.dumps({"target": {"hosts": []}}))
