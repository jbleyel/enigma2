#!/usr/bin/env python
# -*- coding: utf-8 -*-

from Plugins.Extensions.FontBenchmark.FontBenchmark import runFontBenchmark
from Components.PluginComponent import PluginDescriptor


def startFromMainMenu(menuid, **kwargs):
	if menuid == "mainmenu":  # Starting from main menu.
		return [("Font Benchmark", runFontBenchmark, "fonttest", 100)]
	return []


def Plugins(path, **kwargs):
	plugin = [
		PluginDescriptor(name="Font Benchmark", description="Font Benchmark", where=PluginDescriptor.WHERE_MENU, fnc=startFromMainMenu)
	]
	return plugin
