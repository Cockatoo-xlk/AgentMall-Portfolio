"""Container-local bridge. Compose publishes this socket on host loopback only."""

import asyncio


async def bridge(reader, writer):
    other = None
    try:
        remote, other = await asyncio.open_connection("127.0.0.1", 8001)

        async def copy(source, destination):
            try:
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()
            finally:
                destination.close()

        await asyncio.gather(copy(reader, other), copy(remote, writer))
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()
        if other:
            other.close()


async def serve_child(command, *, seconds=1200):
    import os
    import signal
    from pathlib import Path

    if not Path("/.dockerenv").exists():
        raise RuntimeError(
            "Owned container required; host service must bind loopback directly"
        )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    process = await asyncio.create_subprocess_exec(
        *command, start_new_session=True, env=dict(os.environ)
    )
    proxy = None
    wait = asyncio.create_task(process.wait())
    stopping = asyncio.create_task(stop.wait())
    try:
        proxy = await asyncio.start_server(bridge, "0.0.0.0", 18001)
        await asyncio.wait(
            [wait, stopping], timeout=seconds, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        if proxy:
            proxy.close()
            await proxy.wait_closed()
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 15)
            except TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        stopping.cancel()
        await asyncio.gather(stopping, wait, return_exceptions=True)
        for sig, handler in previous.items():
            loop.remove_signal_handler(sig)
            signal.signal(sig, handler)
    return process.returncode
