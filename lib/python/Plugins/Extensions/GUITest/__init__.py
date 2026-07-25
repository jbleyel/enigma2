from gettext import bindtextdomain, dgettext, gettext

from Components.International import international
from Tools.Directories import SCOPE_PLUGINS, resolveFilename

PluginLocaleDomain = "GUITest"
PluginLocalePath = "Extensions/GUITest/locale"


def localeInit():
	localePath = resolveFilename(SCOPE_PLUGINS, PluginLocalePath)
	bindtextdomain(PluginLocaleDomain, localePath)


def _(txt):
	if dgettext(PluginLocaleDomain, txt):
		return dgettext(PluginLocaleDomain, txt)
	else:
		print(f"[{PluginLocaleDomain}] Falling back to default translation for '{txt}'.")
		return gettext(txt)


international.addCallback(localeInit)
