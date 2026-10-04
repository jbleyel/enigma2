# Enigma2 Python Code Style Guide

Not all files in the codebase follow these rules — when editing legacy code, apply rules only to the lines you touch, unless a full cleanup is planned.

---

## General rules

1. Write human readable code.
2. Write code so that it looks like it was written by a human, the same human who wrote the rest of the code.
3. Use variable names that explain what the variable is for and what it does.
4. Keep UI components consistent, coherent and familiar with all the other UI code.
5. Write code that flows in a logical progression and does not require jumping all over the current and other modules to make sense.
6. Don't create a mess of modules where the code is not being shared.
7. Don't define static items in a module that doesn't use them and force an import into the module that does use them.
8. Don't create a method if the code is only a few lines long and the method is only used once.
9. Use `Screens/Menu.py` and `Screens/Setup.py` as reference examples for screens.
10. When creating new code, tell the skinners what they need to do to skin it.
11. Use screen variables that allow screens to be shared or "panel"ed as appropriate.
12. Don't use Python reserved words or builtin names as variable names.
13. Follow PEP 8. Not every PEP 8 rule is used, but most are; see [PEP 8 rules enforced by autopep8](#pep-8-rules-enforced-by-autopep8) below.

---

## Indentation

Tabs, not spaces.  
`W191` (indentation contains tabs) is explicitly ignored in ruff.

```python
class MyScreen(Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.myValue = 0
```

---

## Naming conventions

### Classes

`PascalCase`

```python
class MyScreen(Screen):
class ConfigListScreen:
class MultiContentTemplateParser(TemplateParser):
```

### Functions and methods

`camelCase`

```python
def createMenuList(self):
def selectionChanged(self):
def addItem(self, element):
```

### Module-level constants

`UPPER_SNAKE_CASE` — immutable values that represent fixed configuration, indices, or flags.

```python
MENU_TEXT = 0
MENU_MODULE = 1
ALLOW_SUSPEND = False
MODULE_NAME = __name__.split(".")[-1]
```

### Module-level variables (mutable)

`camelCase` — dictionaries, lists, or other state that changes at runtime.

```python
domScreens = {}
windowStyles = {}
scrollLabelStyle = {}
```

### Instance variables

`self.camelCase`

```python
self.menuList = []
self.pluginLanguageDomain = None
self.timerEntry = None
```

### Private / internal

Prefix with a single underscore `_`.

```python
self._dynPhase = 0
self._dynTimer = eTimer()

def _updateDynamicStack(self):
    pass
```

### Parameters

`camelCase`, same as local variables.

```python
def addFunctionTimer(key, name, entryFunction, cancelFunction, useOwnThread=False):
```

---

## Backward compatibility — do not rename

Some identifiers are part of the public API and **must not be renamed**, even if they violate style rules, because external plugins and skins depend on them by name.

### Screen widget keys

`self["name"]` keys are referenced both in the skin XML and by external plugins.  
Renaming them silently breaks all plugins that access them.

```python
# self["list"] is used in skin XML as name="list" and by plugins as screen["list"]
self["list"] = List(entries)
self["key_red"] = StaticText(_("Exit"))
```

### Public API methods

Methods that are called by the framework, overridden by subclasses, or called from plugins must keep their existing names, regardless of case style.

Common examples:
- `selectionChanged` — called by listbox components
- `layoutFinished` — called by the screen framework
- `ok`, `cancel` — mapped to key actions
- `createSummary` — called by the screen framework for LCD summary screens

### Class-level skin attributes

These attributes are read by the framework and must not be renamed:

| Attribute      | Purpose                                      |
| -------------- | -------------------------------------------- |
| `skin`         | Inline skin XML string                       |
| `skinName`     | List of skin fallback names                  |
| `ALLOW_SUSPEND` | Controls standby/shutdown permission        |
| `ENABLE_RESUME_AFTER_POWEROFF` | Wakeup behavior              |

### Config paths

`config.x.y.z` paths are persisted to disk and used by plugins.  
Never rename a config key once it has been released — doing so discards saved user settings.

---

## Import order

Defined by `pyproject.toml` (`[tool.isort]`).  
Five sections, in this order, with a blank line between each group:

| Section       | Contents                                             |
| ------------- | ---------------------------------------------------- |
| `STDLIB`      | Python standard library                              |
| `ENIGMA`      | `enigma` C++ extension (`from enigma import ...`)    |
| `THIRDPARTY`  | `skin`, `Components.*`, `Screens.*`, `Tools.*`       |
| `FIRSTPARTY`  | `Plugins.*`                                          |
| `LOCALFOLDER` | Relative imports (rare)                              |

Within each section, imports are sorted alphabetically (case-sensitive).  
Multiple names from the same module go on one line, sorted alphabetically.

```python
# STDLIB
from gettext import dgettext
from os.path import getmtime, isdir, isfile

# ENIGMA
from enigma import eTimer, eWindowStyleManager

# THIRDPARTY — skin, Components, Screens, Tools (alphabetical across all)
from skin import menus
from Components.ActionMap import HelpableActionMap, HelpableNumberActionMap
from Components.config import ConfigDictionarySet, NoSave, config, configfile
from Components.Label import Label
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Components.SystemInfo import BoxInfo, getBoxDisplayName
from Screens.Screen import Screen, ScreenSummary
from Screens.Setup import Setup
from Tools.BoundFunction import boundFunction
from Tools.Directories import SCOPE_GUISKIN, SCOPE_SKINS, fileReadXML, resolveFilename
from Tools.LoadPixmap import LoadPixmap

# FIRSTPARTY
from Plugins.Plugin import PluginDescriptor
```

**No multiple modules on one line** (`import os, sys` → `E401`).

### Prefer explicit `from` imports

Always import names directly. Do not use the bare `import module` form and then access names via dotted path.

```python
# Bad
import os
if os.path.exists(path):
    os.path.join(a, b)

# Good
from os.path import exists, join as pathjoin
if exists(path):
    pathjoin(a, b)
```

```python
# Bad
import os
import sys

# Good
from os import listdir, unlink
from os.path import dirname, isfile, join as pathjoin
from sys import argv
```

This applies to stdlib, enigma, and all enigma2 modules alike.  
Exception: if a module has too many names to list, or the dotted form is genuinely clearer in context, the bare import is acceptable — but this is rare.

### No wildcard imports

`from module import *` is not allowed. It pollutes the namespace and makes it impossible to tell where a name comes from.

```python
# Bad
from Components.config import *
from enigma import *

# Good
from Components.config import ConfigBoolean, ConfigSelection, config
from enigma import eTimer, eListbox
```

Ruff enforces this via `F401` (unused names) and `F821` (undefined names), which wildcard imports routinely mask.

### Translation builtins

`_`, `ngettext`, and `pgettext` are declared as builtins in `pyproject.toml`.  
Do not import them — they are always available.

```python
# Correct — no import needed
label = _("Settings")
```

---

## Code patterns

### Single return

Use a single `return` at the end of a function where possible.  
Don't force it if early returns keep the code easier to read.

```python
# Bad
def getServiceName(self, serviceReference):
	if serviceReference is None:
		return ""
	info = eServiceCenter.getInstance().info(serviceReference)
	if info is None:
		return ""
	return info.getName(serviceReference)

# Good
def getServiceName(self, serviceReference):
	serviceName = ""
	info = serviceReference and eServiceCenter.getInstance().info(serviceReference)
	if info:
		serviceName = info.getName(serviceReference)
	return serviceName
```

### List comprehensions

Use list comprehensions where possible.  
Inside a comprehension the loop variable is always `x`.

```python
# Bad
choices = []
for adapter in adapters:
	if adapter.isActive:
		choices.append((adapter.name, adapter.description))

# Good
choices = [(x.name, x.description) for x in adapters if x.isActive]
```

### Tuple or set instead of list

Use a tuple for fixed sequences and a set for membership tests where possible.  
A list is only needed when the content changes.

```python
# Bad
if mode in ["auto", "manual", "off"]:
	pass
for key in ["red", "green", "yellow", "blue"]:
	pass

# Good
if mode in ("auto", "manual", "off"):
	pass
for key in ("red", "green", "yellow", "blue"):
	pass

SKIP_EXTENSIONS = {".tmp", ".bak", ".swp"}
if extension in SKIP_EXTENSIONS:
	pass
```

---

## PEP 8 rules enforced by autopep8

The following rule codes are applied automatically. Violations in new code should be avoided.

### E401 — one import per line

```python
# Bad
import os, sys

# Good
import os
import sys
```

### E502 — redundant backslash inside brackets

```python
# Bad
result = (value1 + \
          value2)

# Good
result = (value1 +
          value2)
```

### E251 / E252 — spaces around parameter defaults

```python
# Bad
def foo(x =1, y: int=2):

# Good — no spaces for plain defaults, spaces around annotated defaults
def foo(x=1, y: int = 2):
```

### E20x — whitespace before/after brackets

```python
# Bad
spam( ham[1], { eggs: 2 } )
list [0]

# Good
spam(ham[1], {"eggs": 2})
list[0]
```

### E211 — whitespace before `(` or `[`

```python
# Bad
spam (1)
dct ['key']

# Good
spam(1)
dct['key']
```

### E225 / E226 / E227 / E228 — whitespace around operators

```python
# Bad
x=1
y =x+1
flags=a|b

# Good
x = 1
y = x + 1
flags = a | b
```

### E231 — whitespace after `,`, `;`, `:`

```python
# Bad
a = (1,2,3)
d = {"a":1}

# Good
a = (1, 2, 3)
d = {"a": 1}
```

### E241 / E242 — multiple spaces or tab after `,`

```python
# Bad
a = (1,  2,	3)

# Good
a = (1, 2, 3)
```

### E261 / E262 — inline comment format

```python
# Bad
x = 1 # comment
x = 1  #comment
x = 1  ## comment

# Good — two spaces before, one space after #
x = 1  # comment
```

### E701 — multiple statements on one line (colon)

```python
# Bad
if x: pass
for i in l: print(i)

# Good
if x:
    pass
for i in l:
    print(i)
```

### E301 / E302 / E303 / E304 / E305 / E306 — blank lines

```python
# E302: two blank lines before top-level class or function
def foo():
    pass


def bar():       # two blank lines before
    pass


class MyClass:   # two blank lines before
    pass


# E301: one blank line before a method inside a class
class MyClass:
    def method_a(self):
        pass

    def method_b(self):   # one blank line before
        pass


# E303: max two blank lines (three or more → error)
# E304: no blank line between decorator and def
@decorator
def foo():       # no blank line after decorator
    pass


# E305: two blank lines after last function/class definition before module-level code
class Foo:
    pass


x = 1            # two blank lines after class


# E306: one blank line before nested function/class
def outer():
    x = 1

    def inner():  # one blank line before nested def
        pass
```

### W291 / W292 / W293 / W391 — trailing whitespace and file endings

- `W291` — no trailing spaces on non-empty lines
- `W292` — file must end with a newline
- `W293` — no trailing whitespace on blank lines
- `W391` — no blank line at the very end of the file

---

## Ruff rules

Configuration in `pyproject.toml`:

```toml
[tool.ruff]
builtins = ["_", "ngettext", "pgettext"]
select = ["E", "F", "W"]
ignore = ["W191", "E501"]
```

| Ignored rule | Reason                                              |
| ------------ | --------------------------------------------------- |
| `W191`       | Tabs are the required indentation style             |
| `E501`       | Line length is not enforced                         |

### Key F (Pyflakes) rules that ruff enforces

| Rule   | Description                                          |
| ------ | ---------------------------------------------------- |
| `F401` | Imported name is unused — remove it or add `# noqa F401` if it is a re-export |
| `F811` | Name re-defined in the same scope (e.g. duplicate import) |
| `F821` | Undefined name used                                  |
| `F841` | Local variable is assigned but never used            |
| `F401` with `# noqa` | Use `# noqa F401` when an import is intentionally re-exported |

```python
# Intentional re-export — suppress F401
from Tools.Directories import resolveFilename  # noqa F401
```

### Suppressing a rule for one line

```python
x = unused_var  # noqa F841
from module import name  # noqa F401
```

Use sparingly — only when the suppression is genuinely correct, not to silence a real bug.

---

## Testing

1. Test your changes. Then test them again.
2. Test as many options as possible, not just your personal configuration. The code is not just for you.
3. If you want others to test your code, give them a test plan.
4. If you can't test all the options your code addresses, ask for testing help. Tell the helpers what you need tested, what to expect and what not to expect.
5. If you ask others to test, freeze that version of the code so you can verify their issue reports. Then confirm that their issues are fixed in the next test version.
6. If you are testing hardware drivers or hardware-related code, make sure you have enough test devices to reasonably test it.
