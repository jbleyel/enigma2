# Enigma2 FunctionTimer Example

This document explains how to use **FunctionTimer** in Enigma2 to create and manage background tasks.  
FunctionTimers allow you to register Python functions that can be executed manually or automatically at scheduled times.  
They are useful for background operations like data updates, monitoring, or maintenance jobs.

---

## Overview

The `addFunctionTimer()` API from the Enigma2 **Scheduler** module lets you register timed functions.  
Each timer can:

- Run in a **Scheduler-managed background thread** (`useOwnThread=False`) — the Scheduler creates a `FunctionTimerThread`; the entry function receives only `(timerEntry)` and its return value is passed to the callback.
- Run with **self-managed async execution** (`useOwnThread=True`) — the entry function receives `(callbackFunction, timerEntry)` and is responsible for calling `callbackFunction(success)` when the work is complete (e.g. via `deferToThread`).
- Support **cancel** functions called when a running timer is stopped
- Safely terminate running loops via a shared stop flag

---

## Example Code

```python
from time import sleep
from twisted.internet.threads import deferToThread
from Scheduler import addFunctionTimer

TASK_ACTIVE = False
TASK_STOP = False


class Tasktester:
    def __init__(self):
        self.timerEntry = None
        self.callback = None

    def taskFinished(self, result):
        """Called by Twisted when deferToThread completes successfully."""
        print("taskFinished", result)
        if self.callback and callable(self.callback):
            self.callback(result)

    def taskError(self, failure):
        """Called by Twisted when deferToThread raises an exception."""
        print("taskError", failure)
        if self.callback and callable(self.callback):
            self.callback(False)

    def runTask(self, timerEntry):
        """The actual worker function — runs in a background thread in both modes."""
        print("#####TASK runTask=", timerEntry)
        global TASK_ACTIVE, TASK_STOP
        TASK_ACTIVE, TASK_STOP = True, False
        loop = 10
        while loop > 0 and not TASK_STOP:
            print("#####TASK operation artificially delayed by 5 seconds")
            sleep(5)
            loop -= 1
            print("#####TASK is still running, TASK_STOP=", TASK_STOP)
        TASK_ACTIVE, TASK_STOP = False, False
        print("#####TASK has been successfully stopped")
        return True

    def ownthreadedTask(self, callbackFunction, timerEntry):
        """useOwnThread=True: called in the main thread; must call callbackFunction(success) when done."""
        self.callback = callbackFunction
        self.timerEntry = timerEntry
        d = deferToThread(self.runTask, timerEntry)
        d.addCallback(self.taskFinished)
        d.addErrback(self.taskError)
        return True


tasktester = Tasktester()


def startThreadedTask(timerEntry):
    """useOwnThread=False: called by FunctionTimerThread; return value is passed to the callback."""
    print("#####Starting background-threaded TASK...", timerEntry)
    return tasktester.runTask(timerEntry)


def startOwnThreadedTask(callbackFunction, timerEntry):
    """useOwnThread=True: called in the main thread; manages its own async execution."""
    print("#####Starting own-threaded TASK...", callbackFunction, timerEntry)
    return tasktester.ownthreadedTask(callbackFunction, timerEntry)


def stopTask():
    """Cancel function — called with no arguments when the timer is stopped."""
    print("#####TASKSTOP received!")
    global TASK_STOP
    TASK_STOP = True


# Register two example FunctionTimers
addFunctionTimer(
    "Tasktester bgThread",
    "Test timer running in a Scheduler-managed background thread",
    startThreadedTask,
    stopTask,
    useOwnThread=False
)

addFunctionTimer(
    "Tasktester ownThread",
    "Test timer running in its own self-managed thread",
    startOwnThreadedTask,
    stopTask,
    useOwnThread=True
)
```


---

## How It Works

### addFunctionTimer()
Registers a new timer entry with the Scheduler.

```
addFunctionTimer(key, name, entryFunction, cancelFunction, useOwnThread=False)
```

| Parameter        | Description                                                                    |
| ---------------- | ------------------------------------------------------------------------------ |
| `key`            | Unique string identifier used to look up the timer in the Scheduler            |
| `name`           | Human-readable display name of the timer                                       |
| `entryFunction`  | Called when the timer fires (signature depends on `useOwnThread`, see below)   |
| `cancelFunction` | Called with no arguments when the timer is cancelled while running             |
| `useOwnThread`   | Controls how the entry function is invoked (see below)                         |

### Entry function signatures

| `useOwnThread` | Invocation                                        | Who calls the callback?                         |
| -------------- | ------------------------------------------------- | ----------------------------------------------- |
| `False`        | `entryFunction(timerEntry)` in a `FunctionTimerThread` | The thread calls the Scheduler callback with the return value |
| `True`         | `entryFunction(callbackFunction, timerEntry)` in the main thread | The function must call `callbackFunction(success)` when done |

### Cancel function signature

The cancel function is always called with **no arguments**:
```python
def stopTask():
    global TASK_STOP
    TASK_STOP = True
```

---

## Task Execution Flow

```
┌───────────────────────────┐
│  addFunctionTimer()       │
└────────────┬──────────────┘
             │
             ▼
   ┌──────────────────┐
   │ Timer Triggered  │
   └────────┬─────────┘
            │
            ├── useOwnThread=False ──► FunctionTimerThread created
            │                          entryFunction(timerEntry) runs in thread
            │                          return value passed to functionTimerCallback
            │
            └── useOwnThread=True ───► entryFunction(callbackFunction, timerEntry)
                                       called in main thread
                                       function must call callbackFunction(success)
                                       when the async work is complete

┌────────────────────────────────────┐
│ Task loop (sleep / repeat)         │
│   - Checks TASK_STOP flag          │
│   - Performs background operation  │
└────────────────────────────────────┘
            │
            ▼
     stopTask() called?
            │
            ▼
┌───────────────────────────┐
│ TASK_STOP = True          │
│ Loop exits gracefully     │
│ functionTimerCallback()   │
└───────────────────────────┘
```

---

## Stop / Cancel Handling

When a running timer is cancelled, the Scheduler calls `cancelFunction()` with no arguments.
Use a shared global flag to end the loop safely:

```python
def stopTask():
    global TASK_STOP
    TASK_STOP = True
```

This avoids abruptly killing threads and ensures a clean exit from running tasks.

---

## Retry Support

The Scheduler supports automatic retries when a function timer fails.  
Retry behavior is configured per timer entry (not via `addFunctionTimer`):

| Field                  | Default | Description                                    |
| ---------------------- | ------- | ---------------------------------------------- |
| `functionRetryCount`   | `0`     | Number of retries (0 = disabled)               |
| `functionRetryDelay`   | `5`     | Minutes between retries                        |
| `functionStandby`      | `0`     | `0` = always run, `1` = standby only, `2` = online only |
| `functionStandbyRetry` | `False` | If `True`, retry when standby condition is met |
