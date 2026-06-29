#!/usr/bin/env python3
"""
Scan all HelpableActionMap definitions and update GlobalStrings.py
with help texts that are not yet present, sorted alphabetically.

GlobalStrings.py must contain these markers:
    class GlobalStrings():
        # START
        ...constants...
        # END

    def reloadStrings(self):
        self.strings = {
            # START
            ...dict entries...
            # END
        }

Usage:
    python3 tools/get_global_strings.py               # add strings with count >= 3
    python3 tools/get_global_strings.py --min-count 5 # only 5+ occurrences
    python3 tools/get_global_strings.py --dry-run     # show without writing
    python3 tools/get_global_strings.py --report      # frequency report only
"""

import argparse
import ast
import os
import re
from collections import defaultdict


TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(TOOLS_DIR, "..", "lib", "python"))
GLOBAL_STRINGS_PATH = os.path.join(ROOT_DIR, "GlobalStrings.py")

CONST_START = "\t# START\n"
CONST_END = "\n\t# END"
STR_START = "\t\t\t# START\n"
STR_END = "\n\t\t\t# END"


def to_constant_name(text):
	return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def extract_help_string(node):
	if (
		isinstance(node, ast.Call)
		and isinstance(node.func, ast.Name)
		and node.func.id == "_"
		and len(node.args) == 1
		and isinstance(node.args[0], ast.Constant)
		and isinstance(node.args[0].value, str)
	):
		return node.args[0].value
	return None


def collect_subclass_names(root_dir):
	"""Find all class names that inherit (directly or indirectly) from HelpableActionMap."""
	known = {"HelpableActionMap", "HelpableNumberActionMap"}
	changed = True
	# iterate until no new subclasses found (handles indirect inheritance)
	while changed:
		changed = False
		for dirpath, _, filenames in os.walk(root_dir):
			for filename in sorted(filenames):
				if not filename.endswith(".py"):
					continue
				path = os.path.join(dirpath, filename)
				try:
					with open(path, encoding="utf-8") as f:
						source = f.read()
					tree = ast.parse(source, filename=path)
				except Exception:
					continue
				for node in ast.walk(tree):
					if not isinstance(node, ast.ClassDef):
						continue
					bases = set()
					for base in node.bases:
						if isinstance(base, ast.Name):
							bases.add(base.id)
						elif isinstance(base, ast.Attribute):
							bases.add(base.attr)
					if bases & known and node.name not in known:
						known.add(node.name)
						changed = True
	return known


def collect_help_strings(root_dir):
	helpable_classes = collect_subclass_names(root_dir)
	counts = defaultdict(int)

	for dirpath, _, filenames in os.walk(root_dir):
		for filename in sorted(filenames):
			if not filename.endswith(".py"):
				continue
			path = os.path.join(dirpath, filename)
			try:
				with open(path, encoding="utf-8") as f:
					source = f.read()
				tree = ast.parse(source, filename=path)
			except Exception as e:
				print(f"Warning: {path}: {e}")
				continue

			for node in ast.walk(tree):
				if not isinstance(node, ast.Call):
					continue
				func = node.func
				name = None
				if isinstance(func, ast.Name):
					name = func.id
				elif isinstance(func, ast.Attribute):
					name = func.attr
				if name not in helpable_classes:
					continue

				actions_node = None
				if len(node.args) >= 3:
					actions_node = node.args[2]
				for kw in node.keywords:
					if kw.arg == "actions":
						actions_node = kw.value
						break

				if not isinstance(actions_node, ast.Dict):
					continue

				for key, value in zip(actions_node.keys, actions_node.values):
					if not isinstance(value, ast.Tuple) or len(value.elts) < 2:
						continue
					text = extract_help_string(value.elts[1])
					if text:
						counts[text] += 1

	return counts


def parse_existing(content):
	"""Parse constants and strings blocks, return name -> text mapping."""
	c_start = content.index(CONST_START) + len(CONST_START)
	c_end = content.index(CONST_END)
	const_block = content[c_start:c_end]

	s_start = content.index(STR_START) + len(STR_START)
	s_end = content.index(STR_END)
	str_block = content[s_start:s_end]

	# name -> text from the strings dict
	name_to_text = {}
	for m in re.finditer(r'^\t\t\tself\.([A-Z_]+): _\("([^"]+)"\),?\s*$', str_block, re.MULTILINE):
		name_to_text[m.group(1)] = m.group(2)

	return name_to_text


def build_blocks(name_to_text):
	"""Build constants and strings blocks sorted alphabetically, integers renumbered."""
	sorted_names = sorted(name_to_text)

	const_lines = [
		"\t" + name + " = " + str(i + 1)
		for i, name in enumerate(sorted_names)
	]

	str_lines = []
	last = len(sorted_names) - 1
	for i, name in enumerate(sorted_names):
		text = name_to_text[name]
		comma = "," if i < last else ""
		str_lines.append('\t\t\tself.' + name + ': _("' + text + '")' + comma)

	return "\n".join(const_lines), "\n".join(str_lines)


def update_file(content, const_block, str_block):
	c_start = content.index(CONST_START) + len(CONST_START)
	c_end = content.index(CONST_END)
	content = content[:c_start] + const_block + content[c_end:]

	s_start = content.index(STR_START) + len(STR_START)
	s_end = content.index(STR_END)
	content = content[:s_start] + str_block + content[s_end:]

	return content


if __name__ == "__main__":
	parser = argparse.ArgumentParser(
		description="Update GlobalStrings from HelpableActionMap help texts"
	)
	parser.add_argument(
		"--min-count",
		type=int,
		default=3,
		help="Minimum occurrences to include (default: 3)",
	)
	parser.add_argument(
		"--dry-run",
		action="store_true",
		help="Show what would be added without writing",
	)
	parser.add_argument(
		"--report",
		action="store_true",
		help="Show frequency report only, no changes",
	)
	parser.add_argument(
		"--clean",
		action="store_true",
		help="Remove entries not found in any HelpableActionMap",
	)
	args = parser.parse_args()

	print(f"Scanning {ROOT_DIR} ...")
	counts = collect_help_strings(ROOT_DIR)

	with open(GLOBAL_STRINGS_PATH, encoding="utf-8") as f:
		original = f.read()

	name_to_text = parse_existing(original)
	existing_texts = set(name_to_text.values())

	if args.report:
		print(f"\n{'Count':>5}  String")
		print("-" * 60)
		for text, count in sorted(counts.items(), key=lambda x: -x[1]):
			marker = "  [in GS]" if text in existing_texts else ""
			print(f"{count:5d}  {text!r}{marker}")
		raise SystemExit(0)

	if args.clean:
		found_texts = set(counts.keys())
		removed = [(name, text) for name, text in sorted(name_to_text.items()) if text not in found_texts]
		if not removed:
			print("Nothing to remove.")
			raise SystemExit(0)
		print(f"\nEntries to remove ({len(removed)}):")
		for name, text in removed:
			print(f"  {name}  # {text!r}")
		if not args.dry_run:
			for name, _ in removed:
				del name_to_text[name]
			const_block, str_block = build_blocks(name_to_text)
			new_content = update_file(original, const_block, str_block)
			with open(GLOBAL_STRINGS_PATH, "w", encoding="utf-8") as f:
				f.write(new_content)
			print(f"\nGlobalStrings.py updated: {len(name_to_text)} entries remaining.")
		else:
			print("\n(dry-run, no changes written)")
		raise SystemExit(0)

	added = []
	skipped = 0
	for text, count in sorted(counts.items(), key=lambda x: -x[1]):
		if count < args.min_count:
			skipped += 1
			continue
		if text in existing_texts:
			continue
		name = to_constant_name(text)
		# avoid name collision
		suffix = 2
		base = name
		while name in name_to_text:
			name = base + "_" + str(suffix)
			suffix += 1
		name_to_text[name] = text
		existing_texts.add(text)
		added.append((name, text, count))

	if not added:
		print("GlobalStrings.py is already up to date.")
	else:
		print(f"\nStrings to add ({len(added)}, skipped {skipped} below --min-count {args.min_count}):")
		for name, text, count in added:
			print(f"  [{count:3d}x]  {name}")

		if args.dry_run:
			print("\n(dry-run, no changes written)")
		else:
			const_block, str_block = build_blocks(name_to_text)
			new_content = update_file(original, const_block, str_block)
			with open(GLOBAL_STRINGS_PATH, "w", encoding="utf-8") as f:
				f.write(new_content)
			print(f"\nGlobalStrings.py updated: {len(name_to_text)} entries total.")
