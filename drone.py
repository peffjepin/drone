#!/usr/bin/env python3

import argparse
import os
import pathlib
import signal
import time
import errno


POLL = 1 / 60
DRONES = pathlib.Path.home() / ".local/share/drones"
DRONES.mkdir(exist_ok=True, parents=True)
EXIT = "exit"


def error(msg):
    TERMINAL_RED = "\033[0;31m"
    TERMINAL_RESET = "\033[0m"
    print(f"{TERMINAL_RED}DRONE ERROR: {msg}{TERMINAL_RESET}")
    raise SystemExit(1)


def init_drone(args):
    drones = [d for d in DRONES.iterdir()]
    names = set(d.name for d in drones)

    if args.id is not None:
        id = args.id
    else:
        int_id = 1
        while str(int_id) in names:
            int_id += 1
        id = str(int_id)

    drone = DRONES / id
    running = True

    def stop():
        nonlocal running
        running = False

    print(f"Starting drone at: {drone}")
    signal.signal(signal.SIGINT, lambda *a: stop())
    os.mkfifo(drone)
    fd = os.open(drone, os.O_RDONLY | os.O_NONBLOCK)
    while running:
        try:
            buffer = os.read(fd, args.buffer_size)
        except OSError as exc:
            if exc.errno == errno.EWOULDBLOCK or exc.errno == errno.EAGAIN:
                buffer = None
            else:
                os.close(fd)
                os.unlink(fd)
                raise
        if buffer is not None:
            cmds = buffer.decode("utf-8").splitlines()
            for cmd in cmds:
                if cmd == EXIT:
                    error("received remote exit signal")
                os.system(cmd)
        else:
            time.sleep(POLL)

    os.unlink(drone)


def select_drone(drones, id):
    if not id:
        return drones[0]
    else:
        for drone in drones:
            if drone.name == str(id):
                return drone
    return None


def send_command(args):
    drones = [d for d in DRONES.iterdir()]
    if len(drones) > 1 and args.id is None:
        error(
            "Found multiple drones running and none were selected using `--id`"
        )
    if len(drones) == 0:
        error("Found no drones running")
    if not args.cmd:
        error("No command given")

    drone = select_drone(drones, args.id)
    if drone is None:
        error("Drone with id={args.id} not found")

    fd = os.open(drone, os.O_WRONLY)
    os.write(fd, args.cmd.encode("utf-8"))
    os.close(fd)


def main():
    parser = argparse.ArgumentParser(
        description="a process that you can launch in a terminal that"
        " will execute commands read in from a pipe"
    )

    commands = parser.add_subparsers(
        help="select a command: drone.py {command} --help for more information",
        dest="command")
    init = commands.add_parser(
        "init", help="initialize a new remote process in the current shell"
    )
    send = commands.add_parser(
        "send", help="sends a command to an already running process"
    )
    commands.add_parser(
        "list", help="list the ids of all running drones")
    commands.add_parser(
        "reset", help="invalidate any existing drones")

    init.add_argument(
        "-i", "--id", help="specify an identifier for this instance"
    )
    init.add_argument(
        "-b", "--buffer-size", default=1024, type=int,
        help="expecting commands to fit within buffer [1024]")

    send.add_argument(
        "cmd", help="the command to be executed in the server instance"
    )
    send.add_argument(
        "-i",
        "--id",
        help="select which server instance to send the command to",
    )

    args = parser.parse_args()
    if args.command == "reset":
        for d in DRONES.iterdir():
            try:
                fd = os.open(d, os.O_WRONLY)
                os.write(fd, EXIT.encode("utf-8"))
                os.close(fd)
                os.unlink(d)
            except Exception:
                pass
    elif args.command == "list":
        for d in DRONES.iterdir():
            print(d.name)
    elif args.command == "init":
        init_drone(args)
    elif args.command == "send":
        send_command(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
