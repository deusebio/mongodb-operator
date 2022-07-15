"""Machine Charm specific functions for operating MongoDB."""
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import os
import pwd

from charms.mongodb_libs.v0.helpers import KEY_FILE
from charms.operator_libs_linux.v1 import systemd

# The unique Charmhub library identifier, never change it
LIBID = "6q947ainc54837t38yhuidshahfgw8f"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version.
LIBPATCH = 1

logger = logging.getLogger(__name__)

MONGO_USER = "mongodb"
MONGO_DATA_DIR = "/data/db"


def auth_enabled() -> bool:
    """Checks if mongod service is running with auth enabled."""
    if not os.path.exists("/lib/systemd/system/mongod.service"):
        return False

    with open("/etc/systemd/system/mongod.service", "r") as mongodb_service_file:
        mongodb_service = mongodb_service_file.readlines()

    for _, line in enumerate(mongodb_service):
        # ExecStart contains the line with the arguments to start mongod service.
        if "ExecStart" in line and "--auth" in line:
            return True

    return False


def stop_mongod_service() -> None:
    """Stop the mongod service if running."""
    if not systemd.service_running("mongod.service"):
        return

    logger.debug("stopping mongod.service")
    try:
        systemd.service_stop("mongod.service")
    except systemd.SystemdError as e:
        logger.error("failed to stop mongod.service, error: %s", str(e))
        raise


def start_mongod_service() -> None:
    """Starts the mongod service if stopped."""
    if systemd.service_running("mongod.service"):
        return

    logger.debug("starting mongod.service")
    try:
        systemd.service_start("mongod.service")
    except systemd.SystemdError as e:
        logger.error("failed to enable mongod.service, error: %s", str(e))
        raise


def update_mongod_service(auth: bool, machine_ip: str, replset: str) -> None:
    """Updates the mongod service file with the new options for starting."""
    mongod_start_args = generate_service_args(auth, machine_ip, replset)

    with open("/lib/systemd/system/mongod.service", "r") as mongodb_service_file:
        mongodb_service = mongodb_service_file.readlines()

    # replace start command with our parameterized one
    for index, line in enumerate(mongodb_service):
        if "ExecStart" in line:
            mongodb_service[index] = mongod_start_args

    # systemd gives files in /etc/systemd/system/ precedence over those in /lib/systemd/system/
    # hence our changed file in /etc will be read while maintaining the original one in /lib.
    with open("/etc/systemd/system/mongod.service", "w") as service_file:
        service_file.writelines(mongodb_service)

    # mongod requires permissions to /data/db
    mongodb_user = pwd.getpwnam(MONGO_USER)
    os.chown(MONGO_DATA_DIR, mongodb_user.pw_uid, mongodb_user.pw_gid)

    # changes to service files are only applied after reloading
    systemd.daemon_reload()


def generate_service_args(auth: bool, machine_ip: str, replset: str) -> str:
    """Construct the mongod startup commandline args for systemd.

    Note that commandline arguments take priority over any user set config file options. User
    options will be configured in the config file. MongoDB handles this merge of these two
    options.
    """
    mongod_start_args = [
        "ExecStart=/usr/bin/mongod",
        # bind to localhost and external interfaces
        "--bind_ip",
        f"localhost,{machine_ip}",
        # part of replicaset
        "--replSet",
        f"{replset}",
    ]

    if auth:
        mongod_start_args.extend(
            [
                "--auth",
                # keyFile used for authentication replica set peers, cluster auth, implies user
                # authentication hence we cannot have cluster authentication without user
                # authentication see:
                # https://www.mongodb.com/docs/manual/reference/configuration-options/#mongodb-setting-security.keyFile
                # TODO: replace with x509
                "--clusterAuthMode=keyFile",
                f"--keyFile={KEY_FILE}",
            ]
        )

    mongod_start_args.append("\n")
    mongod_start_args = " ".join(mongod_start_args)

    return mongod_start_args


class ApplicationHostNotFoundError(Exception):
    """Raised when a queried host is not in the application peers or the current host."""