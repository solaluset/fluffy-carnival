#!/usr/bin/env python3

"""
This program turns keyboard backlight off when keyboard is idle
Requires tuxedo-drivers and xinput
"""

import os
import atexit
import shutil
import signal
import asyncio
import threading
import subprocess
from functools import partial
from concurrent.futures import Future


TIMEOUT = 60
TICK_DURATION = 0.01

BASE_DIR = "/sys/devices/platform/tuxedo_keyboard/leds/rgb:kbd_backlight"
COLOR_FILE = BASE_DIR + "/multi_intensity"
BRIGHTNESS_FILE = BASE_DIR + "/brightness"

DATA_DIR = "/etc/kbsv"
SAVED_COLOR_FILE = DATA_DIR + "/saved_color"
SAVED_BRIGHTNESS_FILE = DATA_DIR + "/saved_brightness"

X_PROGRAM = os.path.split(os.readlink(shutil.which("X")))[1]
IGNORE_USERS = ("lightdm",)


async def aout(cmd, **kwargs):
    return await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            check=kwargs.pop("check", True),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            **kwargs,
        ).stdout,
    )


class Session:
    _sessions = {}
    _last_session = None
    _pid_map = {}

    def __init__(self, name: str):
        self.name = name
        self._display = None
        self._task = None
        self._user = None

    async def get_info(self, fields):
        info = {}
        for line in (
            await aout(
                ("loginctl", "show-session")
                + sum((("-p", field) for field in fields), ())
                + (self.name,),
            )
        ).splitlines():
            field, _, value = line.partition("=")
            info[field] = value
        return info

    async def is_active(self) -> bool:
        try:
            info = await self.get_info(("Active", "Seat", "Name"))
        except subprocess.CalledProcessError:
            if self._task:
                self._task.cancel()
            del self._sessions[self.name]
            self._pid_map.pop(self.name, None)
            return False
        self._user = info["Name"]
        if self._user in IGNORE_USERS:
            return False
        return (
            info["Active"] == "yes"
            and info["Seat"]
            and await self.get_display()
        )

    async def get_display(self) -> str:
        if self._display:
            return self._display
        display = (await self.get_info(("Display",)))["Display"]
        if display:
            self._display = display
            return display
        if self.name in self._pid_map:
            display = self._display_from_pid(self._pid_map[self.name])
            if not display:
                del self._pid_map[self.name]
                await BacklightManager.turn_on()
            return display
        return None

    async def listen(self):
        display = await self.get_display()
        env = os.environ.copy()
        env["XAUTHORITY"] = f"/home/{self._user}/.Xauthority"
        env["DISPLAY"] = display
        device = [
            line
            for line in (
                await aout(
                    ("xinput", "list", "--name-only"),
                    env=env,
                )
            ).splitlines()
            if "keyboard" in line
        ][0]
        process = subprocess.Popen(
            ("xinput", "test-xi2", "--root", device),
            text=True,
            stdout=subprocess.PIPE,
            env=env,
        )
        try:
            while await asyncio.get_running_loop().run_in_executor(
                None, process.stdout.readline
            ):
                timer_task.cancel()
                await BacklightManager.turn_on()
        finally:
            process.send_signal(signal.SIGTERM)

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self.listen())

    def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    @classmethod
    async def _bind_pid(cls, pid):
        if pid in cls._pid_map.values():
            return
        try:
            session = (
                (
                    await aout(
                        (
                            "busctl",
                            "call",
                            "org.freedesktop.login1",
                            "/org/freedesktop/login1",
                            "org.freedesktop.login1.Manager",
                            "GetSessionByPID",
                            "u",
                            pid,
                        ),
                    )
                )
                .strip()
                .partition(" ")[2]
                .strip('"')
            )
        except subprocess.CalledProcessError as e:
            cls._pid_map[e] = pid
        else:
            cls._pid_map[
                (
                    await aout(
                        (
                            "busctl",
                            "get-property",
                            "org.freedesktop.login1",
                            session,
                            "org.freedesktop.login1.Session",
                            "Id",
                        ),
                    )
                )
                .strip()
                .partition(" ")[2]
                .strip('"')
            ] = pid

    @classmethod
    def _display_from_pid(cls, pid):
        try:
            with open(f"/proc/{pid}/cmdline") as f:
                line = f.read()
        except FileNotFoundError:
            return None
        for arg in line.split("\0"):
            if arg.startswith(":"):
                return arg

    @staticmethod
    async def get_session_names():
        return [
            line.split()[0]
            for line in (
                await aout(("loginctl", "list-sessions", "--no-legend"))
            ).splitlines()
        ]

    @classmethod
    async def refresh_sessions(cls) -> bool:
        if cls._last_session and await cls._last_session.is_active():
            return False
        for session in cls._sessions.copy().values():
            if await session.is_active():
                cls._last_session = session
                await session.start()
                return False
        cls._last_session = None
        for x_pid in (await aout(("pidof", X_PROGRAM), check=False)).split():
            await cls._bind_pid(x_pid)
        refreshed_sessions = await cls.get_session_names()
        for name in refreshed_sessions:
            if name not in cls._sessions:
                cls._sessions[name] = session = Session(name)
                if await session.is_active():
                    cls._last_session = session
                    await session.start()
        return True

    @classmethod
    def stop_sessions(cls):
        for name in list(cls._sessions):
            cls._sessions.pop(name).stop()


class BacklightManager:
    is_off = False
    saved_brightness = 0
    current_brightness = 0
    _current_task = None

    @classmethod
    async def turn_off(cls):
        if cls._current_task:
            if cls._current_task.get_name() != "off":
                cls._current_task.cancel()
            else:
                return
        cls._current_task = asyncio.create_task(cls._turn_off(), name="off")

    @classmethod
    async def turn_on(cls):
        if cls._current_task:
            if cls._current_task.get_name() != "on":
                cls._current_task.cancel()
            else:
                return
        cls._current_task = asyncio.create_task(cls._turn_on(), name="on")

    @classmethod
    async def _turn_off(cls):
        if cls.is_off:
            return
        cls.is_off = True
        with open(BRIGHTNESS_FILE, "r+") as f:
            cls.saved_brightness = int(f.read())
            for i in range(cls.saved_brightness, -1, -1):
                await asyncio.sleep(TICK_DURATION)
                cls.current_brightness = i
                f.write(str(i))
                f.flush()

    @classmethod
    async def _turn_on(cls):
        if not cls.is_off:
            return
        with open(BRIGHTNESS_FILE, "w") as f:
            for i in range(
                cls.current_brightness + 1, cls.saved_brightness + 1
            ):
                await asyncio.sleep(TICK_DURATION)
                f.write(str(i))
                f.flush()
        cls.is_off = False

    @classmethod
    def stop(cls):
        if cls._current_task and not cls._current_task.done():
            cls._current_task.cancel()
            cls.is_off = True


async def timer():
    await asyncio.sleep(TIMEOUT)
    if not await Session.refresh_sessions():
        await BacklightManager.turn_off()


async def main():
    global timer_task

    while is_running:
        timer_task = asyncio.create_task(timer())
        try:
            await timer_task
        except asyncio.CancelledError:
            pass


def at_exit():
    Session.stop_sessions()
    BacklightManager.stop()
    if BacklightManager.is_off:
        brightness = str(BacklightManager.saved_brightness)
        with open(BRIGHTNESS_FILE, "w") as f:
            f.write(brightness)
    else:
        with open(BRIGHTNESS_FILE, "r") as f:
            brightness = f.read()
    with open(SAVED_BRIGHTNESS_FILE, "w") as f:
        f.write(brightness)
    with open(COLOR_FILE, "r") as f1, open(SAVED_COLOR_FILE, "w") as f2:
        f2.write(f1.read())


is_running = True


def shutdown(sig, fr):
    global is_running

    is_running = False
    asyncio.get_running_loop().call_soon_threadsafe(timer_task.cancel)


if __name__ == "__main__":
    atexit.register(at_exit)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.isfile(SAVED_COLOR_FILE):
        with open(SAVED_COLOR_FILE, "r") as f1, open(COLOR_FILE, "w") as f2:
            f2.write(f1.read())
    if os.path.isfile(SAVED_BRIGHTNESS_FILE):
        with open(SAVED_BRIGHTNESS_FILE, "r") as f1, open(
            BRIGHTNESS_FILE, "w"
        ) as f2:
            f2.write(f1.read())

    os.chmod(BRIGHTNESS_FILE, 0o666)

    asyncio.run(main())
