"""Inter-Process Communication using operating system pipes."""

import os


def pipe_communication(message):
    read_fd, write_fd = os.pipe()

    try:
        child_pid = os.fork()

        if child_pid == 0:
            # Child process: receive the message.
            os.close(write_fd)
            with os.fdopen(read_fd, "r") as reader:
                received = reader.read()
            print(f"Child received: {received}", flush=True)
            os._exit(0)

        # Parent process: send the message.
        os.close(read_fd)
        with os.fdopen(write_fd, "w") as writer:
            writer.write(message)

        os.waitpid(child_pid, 0)

        return {
            "message_sent": message,
            "communication": "Successful",
            "method": "OS pipe",
        }

    except Exception:
        raise
