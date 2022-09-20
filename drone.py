#!/usr/bin/env python3

import argparse
import os
import sys
import shlex
import subprocess
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


class Drone:
    def __init__(self, addr, cli):
        self.addr = addr
        self.running = False
        self.cli = cli
        self.current_subprocess = None

        self.watch_dirs = []
        if cli.watch:
            if not cli.on_update:
                error(
                    "Drone was given directories to watch for changes in but "
                    "no command to call in `--on-update`")
            for p in cli.watch.split(","):
                self.watch_dirs.append(pathlib.Path(p))

        self.watch_dict = {}
        self.watch_triggered = False
        self.check_watch_dirs()

    def check_watch_dirs(self):
        for wd in self.watch_dirs:
            for p in wd.iterdir():
                last_edit = p.stat().st_mtime
                record = self.watch_dict.get(p)
                if record is None or record != last_edit:
                    self.watch_triggered = True
                self.watch_dict[p] = last_edit
        self.previous_watch_dirs_check = time.time()

    def run_command(self, cmd):
        print(f"file update detected, running: {cmd}")
        if self.cli.patient:
            subprocess.run(
                shlex.split(cmd), stdout=sys.stdout, stderr=sys.stderr)
        else:
            if self.current_subprocess and self.current_subprocess.poll() is None:
                self.current_subprocess.kill()
            self.current_subprocess = subprocess.Popen(
                shlex.split(cmd), stdout=sys.stdout, stderr=sys.stderr)

    def stop(self, *args):
        self.running = False

    def run(self):
        self.running = True
        print(f"Starting drone at: {self.addr}")
        signal.signal(signal.SIGINT, lambda *a: self.stop())
        try:
            os.mkfifo(self.addr)
        except FileExistsError:
            os.unlink(self.addr)
            os.mkfifo(self.addr)
        fd = os.open(self.addr, os.O_RDONLY | os.O_NONBLOCK)
        while self.running:
            time.sleep(POLL)
            if self.watch_dirs and time.time() > self.previous_watch_dirs_check + self.cli.watch_interval:
                self.check_watch_dirs()
            if self.watch_triggered:
                self.run_command(self.cli.on_update)
                self.watch_triggered = False
            try:
                buffer = os.read(fd, self.cli.buffer_size)
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
                    self.run_command(cmd)

        os.unlink(self.addr)


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

    drone = Drone(DRONES/id, args)
    drone.run()


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
        "-w", "--watch",
        help="comma separated directories to watch for file changes in")
    init.add_argument(
        "-u", "--on-update",
        help="command to run when a file in a watched directory is updated")
    init.add_argument(
        "--watch-interval", type=float, default=0.5,
        help="the interval (s) to check for changes in watched directories [0.5s]")
    init.add_argument(
        "-p", "--patient", action="store_true",
        help="if not set then previous commands will be terminated when a new command is received")
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
