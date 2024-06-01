#!/usr/bin/env python3

"""
This progrma turns keyboard backlight off when keyboard is idle.
Requires tuxedo_keuboard and xinput.
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


BASE_DIR = "/sys/devices/platform/tuxedo_keyboard/leds/rgb:kbd_backlight"
COLOR_FILE = BASE_DIR + "/multi_intensity"
BRIGHTNESS_FILE = BASE_DIR + "/brightness"
TIMEOUT = 60
TICK_DURATION = 0.01
X_PROGRAM = os.path.split(os.readlink(shutil.which("X")))[1]
IGNORE_USERS = ("lightdm",)


async def aout(cmd, **kwargs):
    return await asyncio.get_running_loop().run_in_executor(
        None,
        partial(
            subprocess.check_output,
            cmd,
            text=True,
            stderr=subprocess.DEVNULL,
            **kwargs,
        ),
    )


async def run_as_daemon(func, *args):
    future = Future()
    future.set_running_or_notify_cancel()

    def daemon():
        try:
            result = func(*args)
        except BaseException as e:
            future.set_exception(e)
        else:
            future.set_result(result)

    threading.Thread(target=daemon, daemon=True).start()
    return await asyncio.wrap_future(future)


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
        while await run_as_daemon(process.stdout.readline):
            timer_task.cancel()
            await BacklightManager.turn_on()

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self.listen())

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
        for x_pid in (await aout(("pidof", X_PROGRAM))).split():
            await cls._bind_pid(x_pid)
        refreshed_sessions = await cls.get_session_names()
        for name in refreshed_sessions:
            if name not in cls._sessions:
                cls._sessions[name] = session = Session(name)
                if await session.is_active():
                    cls._last_session = session
                    await session.start()
        return True


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

    while True:
        timer_task = asyncio.create_task(timer())
        try:
            await timer_task
        except asyncio.CancelledError:
            pass


def at_exit():
    BacklightManager.stop()
    with open("/etc/saved_keyboard_state", "r") as f:
        state = f.read().strip()
    if state == "1":
        if BacklightManager.is_off:
            brightness = str(BacklightManager.saved_brightness)
        else:
            with open(BRIGHTNESS_FILE, "r") as f:
                brightness = f.read()
        with open("/etc/saved_keyboard_brightness", "w") as f:
            f.write(brightness)
    with open(COLOR_FILE, "r") as f1, open(
        "/etc/saved_keyboard_color", "w"
    ) as f2:
        f2.write(f1.read())


def sigterm(sig, fr):
    exit(0)


if __name__ == "__main__":
    atexit.register(at_exit)
    signal.signal(signal.SIGTERM, sigterm)

    with open("/etc/saved_keyboard_color", "r") as f1, open(
        COLOR_FILE, "w"
    ) as f2:
        f2.write(f1.read())
    with open("/etc/saved_keyboard_state", "r") as f:
        state = f.read().strip()
    if state == "1":
        with open("/etc/saved_keyboard_brightness", "r") as f1, open(
            BRIGHTNESS_FILE, "w"
        ) as f2:
            f2.write(f1.read())

    os.chmod(BRIGHTNESS_FILE, 0o666)

    asyncio.run(main())
