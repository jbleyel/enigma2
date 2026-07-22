#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# FontBenchmark.py  –  enigma2 font rendering benchmark
#
# Misst renderString() / blit() Performance über die Screen-eigenen Widgets.
# setText() auf einem echten Label ruft intern renderString() auf.
# dumpFontPerfStats() schreibt die C++-Counters ins enigma2 Log.
#
# Requires: font.cpp built with -DFONT_PERF_DEBUG
#
# Install:
#   /usr/lib/enigma2/python/Plugins/Extensions/FontBenchmark/
#       __init__.py
#       plugin.py
#       FontBenchmark.py

from Screens.Screen import Screen
from Components.ActionMap import ActionMap
from Components.Label import Label
from enigma import eTimer
import time

try:
    from enigma import dumpFontPerfStats
except ImportError:
   def dumpFontPerfStats():
       pass


# ── Test data ─────────────────────────────────────────────────────────────────

REDRAW_COUNT = 1000

CHANNEL_NAMES = [
    "Das Erste HD", "ZDF HD", "RTL HD", "SAT.1 HD", "ProSieben HD",
    "kabel eins HD", "VOX HD", "RTL2 HD", "SUPER RTL HD", "n-tv HD",
    "WELT HD", "phoenix HD", "3sat HD", "arte HD", "ZDFneo HD",
    "ZDFinfo HD", "ONE HD", "tagesschau24 HD", "Eurosport 1 HD", "DMAX HD",
    "TLC HD", "Nickelodeon HD", "Disney Channel HD", "MTV HD", "VIVA HD",
    "Comedy Central HD", "Sixx HD", "Das Vierte HD", "Tele 5 HD", "Sport1 HD",
]

EPG_SHORT = (
    "Der Detektiv Derrick und sein Assistent Harry Klein ermitteln in einem "
    "mysteriösen Mordfall im Münchner Umland. Die Spuren führen in die gehobene "
    "Gesellschaft. Spannender Krimi aus der beliebten deutschen Reihe."
)

EPG_LONG = (
    "In dieser packenden Folge der preisgekrönten Krimiserie steht Derrick vor "
    "seinem bisher schwierigsten Fall. Ein angesehener Bankdirektor wird tot in "
    "seiner Villa aufgefunden. Alle Indizien deuten auf Selbstmord hin, doch "
    "Derrick zweifelt. Seine jahrelange Erfahrung sagt ihm, dass hier etwas "
    "nicht stimmt. Gemeinsam mit seinem treuen Assistenten Harry Klein beginnt "
    "er, das Umfeld des Toten zu durchleuchten. Die Ehefrau wirkt seltsam "
    "gefasst, der Geschäftspartner nervös, und die Sekretärin schweigt "
    "beharrlich. Je tiefer Derrick gräbt, desto mehr Geheimnisse kommen ans "
    "Licht. Dunkle Geschäfte, verschwiegene Affären und alte Feindschaften "
    "verweben sich zu einem Netz aus Lügen. Am Ende steht eine Wahrheit, die "
    "niemand erwartet hätte. Mit Horst Tappert und Fritz Wepper. FSK 12. "
) * 3

SUBTITLE_TEXT = "Untertitel: Das ist ein Beispieltext mit Border."

COLOR_TEXT = (
    r"\c00ff0000Rot \c0000ff00Grün \c000000ffBlau \c00ffffffWeiss "
    r"\c00ffff00Gelb \c00ff00ffMagenta \c0000ffffCyan \c00888888Grau"
)

RTL_TEXT = (
    u"مرحبا بكم في النظام "
    u"English mixed with \u0627\u0644\u0639\u0631\u0628\u064a\u0629 "
    u"and back to Latin again."
)


# ── Screen ────────────────────────────────────────────────────────────────────

class FontBenchmarkScreen(Screen):

    skin = """
        <screen name="FontBenchmarkScreen" position="center,center"
                size="900,600" title="Font Benchmark">
            <widget name="status" position="10,10" size="880,50"
                    font="Regular;30" halign="center" valign="center"
                    foregroundColor="#00ffffff" />
            <widget name="bench_label" position="10,70" size="880,300"
                    font="Regular;24" halign="left" valign="top"
                    foregroundColor="#00cccccc" />
            <widget name="results" position="10,380" size="880,200"
                    font="Regular;20" halign="left" valign="top"
                    foregroundColor="#0088ff88" />
        </screen>
    """

    SCENARIOS = [
        ("Channel list", "ASCII, %d Namen x %d redraws" % (len(CHANNEL_NAMES), REDRAW_COUNT)),
        ("EPG short", "~200 Zeichen, wrap"),
        ("EPG long", "~%d Zeichen, wrap" % len(EPG_LONG)),
        ("Subtitle", "%d redraws" % REDRAW_COUNT),
        ("Color text", r"inline \c Farbcodes"),
        ("RTL/mixed", u"Arabisch + Latein"),
    ]

    def __init__(self, session):
        Screen.__init__(self, session)

        self["status"] = Label("Font Benchmark  –  OK zum Starten")
        self["bench_label"] = Label("")
        self["results"] = Label("")

        self["actions"] = ActionMap(
            ["OkCancelActions"],
            {"ok": self.startBenchmark, "cancel": self.close},
            -1,
        )

        self._results = []
        self._scenario = 0
        self._timer = eTimer()
        self._timer.callback.append(self._runNextScenario)

    # ── start ─────────────────────────────────────────────────────────────────

    def startBenchmark(self):
        self._results = []
        self._scenario = 0
        self["status"].setText("Benchmark läuft …")
        self["results"].setText("")
        # kurze Pause damit der Screen neu zeichnet bevor wir beginnen
        self._timer.start(100, True)

    # ── scenario dispatch ─────────────────────────────────────────────────────

    def _runNextScenario(self):
        n = self._scenario
        name, desc = self.SCENARIOS[n]
        self["status"].setText("Szenario %d/%d: %s" % (n + 1, len(self.SCENARIOS), name))

        if n == 0:
            elapsed, calls = self._scenarioChannelList()
        elif n == 1:
            elapsed, calls = self._scenarioText(EPG_SHORT, REDRAW_COUNT)
        elif n == 2:
            elapsed, calls = self._scenarioText(EPG_LONG, 1)
        elif n == 3:
            elapsed, calls = self._scenarioText(SUBTITLE_TEXT, REDRAW_COUNT)
        elif n == 4:
            elapsed, calls = self._scenarioText(COLOR_TEXT, REDRAW_COUNT)
        elif n == 5:
            elapsed, calls = self._scenarioText(RTL_TEXT, REDRAW_COUNT)

        # C++ counters in Log schreiben
        dumpFontPerfStats()

        self._results.append((name, desc, elapsed, calls))
        self._scenario += 1

        if self._scenario < len(self.SCENARIOS):
            self._timer.start(80, True)
        else:
            self._finish()

    # ── scenario helpers ──────────────────────────────────────────────────────

    def _scenarioChannelList(self):
        """
        Viele kurze ASCII-Strings — simuliert Senderlisten-Redraw.
        Wir setzen setText() abwechselnd auf bench_label.
        """
        widget = self["bench_label"]
        t0 = time.monotonic()
        for _ in range(REDRAW_COUNT):
            for name in CHANNEL_NAMES:
                widget.setText(name)
        elapsed = time.monotonic() - t0
        calls = REDRAW_COUNT * len(CHANNEL_NAMES)
        widget.setText("")
        return elapsed, calls

    def _scenarioText(self, text, count):
        """
        Einen Text `count` mal in bench_label schreiben.
        Zwischen jedem Durchlauf leeren damit renderString() immer neu läuft.
        """
        widget = self["bench_label"]
        t0 = time.monotonic()
        for _ in range(count):
            widget.setText(text)
            widget.setText("")   # leeren erzwingt neues render beim nächsten setText
        elapsed = time.monotonic() - t0
        widget.setText("")
        return elapsed, count

    # ── finish ────────────────────────────────────────────────────────────────

    def _finish(self):
        self["status"].setText("Fertig  –  Ergebnisse:")

        lines = []
        for (name, desc, elapsed, calls) in self._results:
            calls = max(calls, 1)
            total_ms = elapsed * 1000.0
            avg_us = elapsed * 1e6 / calls
            line = "%-14s  %7.1f ms  %6.1f µs/call  (%d)" % (
                name, total_ms, avg_us, calls)
            lines.append(line)
            print("[FontBenchmark] " + line + "  [" + desc + "]")

        self["results"].setText("\n".join(lines))

        # finaler kompletter Dump aller C++ Counters
        dumpFontPerfStats()


# ── Plugin glue ───────────────────────────────────────────────────────────────

def runFontBenchmark(session, **kwargs):
    session.open(FontBenchmarkScreen)
