"""예외 메시지·소스 줄·locals 없이 단계와 코드 위치만 남긴다."""

import json
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path


def failure_details(exc, stage):
    frames = []
    tb = exc.__traceback__
    while tb is not None:
        frames.append(
            {
                "file": Path(tb.tb_frame.f_code.co_filename).name,
                "function": tb.tb_frame.f_code.co_name,
                "line": tb.tb_lineno,
            }
        )
        tb = tb.tb_next
    return {
        "failed_stage": stage,
        "exception_type": type(exc).__name__,
        "frames": frames[-8:],
    }


def emit_event(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


@contextmanager
def safe_process_diagnostics():
    """로컬 프로세스의 stderr에도 경고/예외 원문을 쓰지 않는다."""
    old_warning, old_hook = warnings.showwarning, sys.excepthook

    def show_warning(message, category, filename, lineno, file=None, line=None):
        print(
            json.dumps(
                {
                    "event": "warning",
                    "category": category.__name__,
                    "file": Path(filename).name,
                    "line": lineno,
                }
            ),
            file=sys.stderr,
            flush=True,
        )

    def exception_hook(exc_type, exc, tb):
        print(
            json.dumps(
                {"event": "uncaught_exception", **failure_details(exc, "process")}
            ),
            file=sys.stderr,
            flush=True,
        )

    warnings.showwarning, sys.excepthook = show_warning, exception_hook
    try:
        yield
    except BaseException as exc:
        if isinstance(exc, SystemExit) and isinstance(exc.code, (int, type(None))):
            raise
        exception_hook(type(exc), exc, exc.__traceback__)
        raise SystemExit(1) from None
    finally:
        warnings.showwarning, sys.excepthook = old_warning, old_hook
