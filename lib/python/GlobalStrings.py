class GlobalStrings:
	# START
	ACTIVATE_NETWORK_ADAPTER_CONFIGURATION = 1
	ADD_A_NEW_TITLE = 2
	AUDIO_OPTIONS = 3
	CANCEL_ANY_CHANGED_SETTINGS_AND_EXIT = 4
	CANCEL_ANY_CHANGED_SETTINGS_AND_EXIT_ALL_MENUS = 5
	CANCEL_ANY_CHANGED_TAGS_AND_EXIT = 6
	CANCEL_SELECTION = 7
	CANCEL_SERVICE_SELECTION_AND_EXIT = 8
	CANCEL_THE_IMAGE_SELECTION_AND_EXIT = 9
	CANCEL_THE_SELECTION_AND_EXIT = 10
	CHANGE_TO_BOUQUET = 11
	CLOSE_SCREEN = 12
	CLOSE_TASK_LIST = 13
	CLOSE_TASK_VIEW = 14
	CLOSE_THE_CURRENT_SCREEN = 15
	CLOSE_THE_GUI_TEST_MENU_SCREEN = 16
	CLOSE_THE_KEXEC_MULTIBOOT_MANAGER = 17
	CLOSE_THE_SCREEN = 18
	CLOSE_THE_SCREEN_AND_EXIT_ALL_MENUS = 19
	CLOSE_THE_WINDOW = 20
	CLOSE_THIS_SCREEN = 21
	CONTINUE_PLAYBACK = 22
	DELETE_ALL_THE_TEXT = 23
	DIGIT_ENTRY_FOR_SERVICE_SELECTION = 24
	DISPLAY_MORE_INFORMATION_ABOUT_THIS_FILE = 25
	DISPLAY_SELECTION_LIST_AS_A_SELECTION_MENU = 26
	ENTER_NUMBER_TO_JUMP_TO_CHANNEL = 27
	EXIT_EDITOR_AND_DISCARD_ANY_CHANGES = 28
	EXIT_INPUT_DEVICE_SELECTION = 29
	EXIT_MENU = 30
	EXIT_NETWORK_ADAPTER_CONFIGURATION = 31
	EXIT_NETWORK_ADAPTER_SETUP_MENU = 32
	EXIT_NETWORK_INTERFACE_LIST = 33
	EXIT_VIEWER = 34
	FIND_SIMILAR_EVENTS_IN_THE_EPG = 35
	GO_BACK_TO_THE_PREVIOUS_STEP = 36
	KEYBOARD_DATA_ENTRY = 37
	LEAVE_MOVIE_PLAYER = 38
	LETTERBOX_ZOOM = 39
	LIST_EPG_FUNCTIONS = 40
	MENU = 41
	MOVE_DOWN_A_LINE = 42
	MOVE_DOWN_A_PAGE = 43
	MOVE_DOWN_A_PAGE___SCREEN = 44
	MOVE_DOWN_A_SCREEN = 45
	MOVE_THE_CURRENT_ENTRY_DOWN = 46
	MOVE_THE_CURRENT_ENTRY_UP = 47
	MOVE_TO_FIRST_LINE = 48
	MOVE_TO_FIRST_LINE___SCREEN = 49
	MOVE_TO_LAST_LINE = 50
	MOVE_TO_LAST_LINE___SCREEN = 51
	MOVE_TO_NEXT_BOUQUET = 52
	MOVE_TO_PREVIOUS_BOUQUET = 53
	MOVE_TO_THE_FIRST_ITEM_ON_THE_CURRENT_LINE = 54
	MOVE_TO_THE_FIRST_ITEM_ON_THE_FIRST_SCREEN = 55
	MOVE_TO_THE_FIRST_LINE___SCREEN = 56
	MOVE_TO_THE_LAST_ITEM_ON_THE_CURRENT_LINE = 57
	MOVE_TO_THE_LAST_ITEM_ON_THE_LAST_SCREEN = 58
	MOVE_TO_THE_LAST_LINE___SCREEN = 59
	MOVE_TO_THE_NEXT_CATEGORY_IN_THE_LIST = 60
	MOVE_TO_THE_PREVIOUS_CATEGORY_IN_THE_LIST = 61
	MOVE_UP_A_LINE = 62
	MOVE_UP_A_PAGE = 63
	MOVE_UP_A_PAGE___SCREEN = 64
	MOVE_UP_A_SCREEN = 65
	NUMBER_OR_SMS_STYLE_DATA_ENTRY = 66
	OPEN_BOUQUET_SELECTION = 67
	OPEN_MOVIE_SELECTION = 68
	PAUSE_PLAYBACK = 69
	PLAY_THE_SELECTED_SERVICE = 70
	REFRESH_SCREEN = 71
	REFRESH_THE_SCREEN = 72
	RESET_ENTRIES_TO_THEIR_DEFAULT_VALUES = 73
	RESET_THE_ORDER_OF_THE_ENTRIES = 74
	SAVE_ALL_CHANGED_SETTINGS_AND_EXIT = 75
	SAVE_ALL_CHANGED_TAGS_AND_EXIT = 76
	SEEK = 77
	SEEK_BACKWARD_ENTER_TIME = 78
	SEEK_FORWARD_ENTER_TIME = 79
	SELECT_A_MENU_ITEM = 80
	SELECT_CHANNEL_AUDIO = 81
	SELECT_INPUT_DEVICE = 82
	SELECT_INTERFACE = 83
	SELECT_MENU_ENTRY = 84
	SELECT_QUAD_CHANNELS = 85
	SELECT_SHARES = 86
	SELECT_THE_CURRENTLY_HIGHLIGHTED_SERVICE = 87
	SELECT_THE_HIGHLIGHTED_IMAGE_AND_PROCEED_TO_THE_SLOT_SELECTION = 88
	SELECT_THE_HIGHLIGHTED_SLOT_AND_REBOOT = 89
	SHOW_CHANNEL_SELECTION = 90
	SHOW_DETAILS_OF_HIGHLIGHTED_TASK = 91
	SHOW_EVENT_DETAILS = 92
	SHOW_NEXT_COMMIT_LOG = 93
	SHOW_NEXT_PAGE = 94
	SHOW_NEXT_PICTURE = 95
	SHOW_NEXT_SERVICE_INFORMATION_SCREEN = 96
	SHOW_NEXT_SYSTEM_INFORMATION_SCREEN = 97
	SHOW_PREVIOUS_COMMIT_LOG = 98
	SHOW_PREVIOUS_PAGE = 99
	SHOW_PREVIOUS_PICTURE = 100
	SHOW_PREVIOUS_SERVICE_INFORMATION_SCREEN = 101
	SHOW_PREVIOUS_SYSTEM_INFORMATION_SCREEN = 102
	SHOW_THE_INFORMATION_ON_CURRENT_EVENT = 103
	START_AN_INSTANT_RECORDING = 104
	STOP_THE_UPDATE_IF_RUNNING_THEN_EXIT = 105
	SWITCH_BETWEEN_FILE_LIST_PLAY_LIST = 106
	SWITCH_EPG_PAGE_DOWN = 107
	SWITCH_EPG_PAGE_UP = 108
	SWITCH_TO_HDMI_IN_MODE = 109
	SWITCH_TO_THE_LEFT_COLUMN = 110
	SWITCH_TO_THE_RIGHT_COLUMN = 111
	TOGGLE_DISPLAY_OF_THE_INFOBAR = 112
	TOGGLE_MOVE_MODE = 113
	ZOOM_IN_OUT_TV = 114
	ZOOM_OFF = 115
	# END

	def __init__(self):
		self.reloadStrings()

	def reloadStrings(self):
		self.strings = {
			# START
			self.ACTIVATE_NETWORK_ADAPTER_CONFIGURATION: _("Activate network adapter configuration"),
			self.ADD_A_NEW_TITLE: _("Add a new title"),
			self.AUDIO_OPTIONS: _("Open Audio options"),
			self.CANCEL_ANY_CHANGED_SETTINGS_AND_EXIT: _("Cancel any changed settings and exit"),
			self.CANCEL_ANY_CHANGED_SETTINGS_AND_EXIT_ALL_MENUS: _("Cancel any changed settings and exit all menus"),
			self.CANCEL_ANY_CHANGED_TAGS_AND_EXIT: _("Cancel any changed tags and exit"),
			self.CANCEL_SELECTION: _("Cancel the selection"),
			self.CANCEL_SERVICE_SELECTION_AND_EXIT: _("Cancel service selection and exit"),
			self.CANCEL_THE_IMAGE_SELECTION_AND_EXIT: _("Cancel the image selection and exit"),
			self.CANCEL_THE_SELECTION_AND_EXIT: _("Cancel the selection and exit"),
			self.CHANGE_TO_BOUQUET: _("Change to bouquet"),
			self.CLOSE_SCREEN: _("Close screen"),
			self.CLOSE_TASK_LIST: _("Close Task List"),
			self.CLOSE_TASK_VIEW: _("Close Task View"),
			self.CLOSE_THE_CURRENT_SCREEN: _("Close the current screen"),
			self.CLOSE_THE_GUI_TEST_MENU_SCREEN: _("Close the GUI Test menu screen"),
			self.CLOSE_THE_KEXEC_MULTIBOOT_MANAGER: _("Close the Kexec MultiBoot Manager"),
			self.CLOSE_THE_SCREEN: _("Close the screen"),
			self.CLOSE_THE_SCREEN_AND_EXIT_ALL_MENUS: _("Close the screen and exit all menus"),
			self.CLOSE_THE_WINDOW: _("Close the window"),
			self.CLOSE_THIS_SCREEN: _("Close this screen"),
			self.CONTINUE_PLAYBACK: _("Continue playback"),
			self.DELETE_ALL_THE_TEXT: _("Delete all the text"),
			self.DIGIT_ENTRY_FOR_SERVICE_SELECTION: _("Digit entry for service selection"),
			self.DISPLAY_MORE_INFORMATION_ABOUT_THIS_FILE: _("Display more information about this file"),
			self.DISPLAY_SELECTION_LIST_AS_A_SELECTION_MENU: _("Display selection list as a selection menu"),
			self.ENTER_NUMBER_TO_JUMP_TO_CHANNEL: _("Enter number to jump to channel"),
			self.EXIT_EDITOR_AND_DISCARD_ANY_CHANGES: _("Exit editor and discard any changes"),
			self.EXIT_INPUT_DEVICE_SELECTION: _("Exit input device selection."),
			self.EXIT_MENU: _("Exit menu"),
			self.EXIT_NETWORK_ADAPTER_CONFIGURATION: _("Exit network adapter configuration"),
			self.EXIT_NETWORK_ADAPTER_SETUP_MENU: _("Exit network adapter setup menu"),
			self.EXIT_NETWORK_INTERFACE_LIST: _("Exit network interface list"),
			self.EXIT_VIEWER: _("Exit viewer"),
			self.FIND_SIMILAR_EVENTS_IN_THE_EPG: _("Find similar events in the EPG"),
			self.GO_BACK_TO_THE_PREVIOUS_STEP: _("Go back to the previous step"),
			self.KEYBOARD_DATA_ENTRY: _("Keyboard data entry"),
			self.LEAVE_MOVIE_PLAYER: _("Leave movie player"),
			self.LETTERBOX_ZOOM: _("LetterBox zoom"),
			self.LIST_EPG_FUNCTIONS: _("List available EPG functions"),
			self.MENU: _("Menu"),
			self.MOVE_DOWN_A_LINE: _("Move down a line"),
			self.MOVE_DOWN_A_PAGE: _("Move down a page"),
			self.MOVE_DOWN_A_PAGE___SCREEN: _("Move down a page / screen"),
			self.MOVE_DOWN_A_SCREEN: _("Move down a screen"),
			self.MOVE_THE_CURRENT_ENTRY_DOWN: _("Move the current entry down"),
			self.MOVE_THE_CURRENT_ENTRY_UP: _("Move the current entry up"),
			self.MOVE_TO_FIRST_LINE: _("Move to first line"),
			self.MOVE_TO_FIRST_LINE___SCREEN: _("Move to first line / screen"),
			self.MOVE_TO_LAST_LINE: _("Move to last line"),
			self.MOVE_TO_LAST_LINE___SCREEN: _("Move to last line / screen"),
			self.MOVE_TO_NEXT_BOUQUET: _("Move to next bouquet"),
			self.MOVE_TO_PREVIOUS_BOUQUET: _("Move to previous bouquet"),
			self.MOVE_TO_THE_FIRST_ITEM_ON_THE_CURRENT_LINE: _("Move to the first item on the current line"),
			self.MOVE_TO_THE_FIRST_ITEM_ON_THE_FIRST_SCREEN: _("Move to the first item on the first screen"),
			self.MOVE_TO_THE_FIRST_LINE___SCREEN: _("Move to the first line / screen"),
			self.MOVE_TO_THE_LAST_ITEM_ON_THE_CURRENT_LINE: _("Move to the last item on the current line"),
			self.MOVE_TO_THE_LAST_ITEM_ON_THE_LAST_SCREEN: _("Move to the last item on the last screen"),
			self.MOVE_TO_THE_LAST_LINE___SCREEN: _("Move to the last line / screen"),
			self.MOVE_TO_THE_NEXT_CATEGORY_IN_THE_LIST: _("Move to the next category in the list"),
			self.MOVE_TO_THE_PREVIOUS_CATEGORY_IN_THE_LIST: _("Move to the previous category in the list"),
			self.MOVE_UP_A_LINE: _("Move up a line"),
			self.MOVE_UP_A_PAGE: _("Move up a page"),
			self.MOVE_UP_A_PAGE___SCREEN: _("Move up a page / screen"),
			self.MOVE_UP_A_SCREEN: _("Move up a screen"),
			self.NUMBER_OR_SMS_STYLE_DATA_ENTRY: _("Number or SMS style data entry"),
			self.OPEN_BOUQUET_SELECTION: _("Open Bouquet selection"),
			self.OPEN_MOVIE_SELECTION: _("Open Movie Selection"),
			self.PAUSE_PLAYBACK: _("Pause playback"),
			self.PLAY_THE_SELECTED_SERVICE: _("Play the selected service"),
			self.REFRESH_SCREEN: _("Refresh screen"),
			self.REFRESH_THE_SCREEN: _("Refresh the screen"),
			self.RESET_ENTRIES_TO_THEIR_DEFAULT_VALUES: _("Reset entries to their default values"),
			self.RESET_THE_ORDER_OF_THE_ENTRIES: _("Reset the order of the entries"),
			self.SAVE_ALL_CHANGED_SETTINGS_AND_EXIT: _("Save all changed settings and exit"),
			self.SAVE_ALL_CHANGED_TAGS_AND_EXIT: _("Save all changed tags and exit"),
			self.SEEK: _("Seek"),
			self.SEEK_BACKWARD_ENTER_TIME: _("Seek backward (enter time)"),
			self.SEEK_FORWARD_ENTER_TIME: _("Seek forward (enter time)"),
			self.SELECT_A_MENU_ITEM: _("Select a menu item"),
			self.SELECT_CHANNEL_AUDIO: _("Select channel audio"),
			self.SELECT_INPUT_DEVICE: _("Select input device."),
			self.SELECT_INTERFACE: _("Select interface"),
			self.SELECT_MENU_ENTRY: _("Select menu entry"),
			self.SELECT_QUAD_CHANNELS: _("Select Quad Channels"),
			self.SELECT_SHARES: _("Select Shares"),
			self.SELECT_THE_CURRENTLY_HIGHLIGHTED_SERVICE: _("Select the currently highlighted service"),
			self.SELECT_THE_HIGHLIGHTED_IMAGE_AND_PROCEED_TO_THE_SLOT_SELECTION: _("Select the highlighted image and proceed to the slot selection"),
			self.SELECT_THE_HIGHLIGHTED_SLOT_AND_REBOOT: _("Select the highlighted slot and reboot"),
			self.SHOW_CHANNEL_SELECTION: _("Show channel selection"),
			self.SHOW_DETAILS_OF_HIGHLIGHTED_TASK: _("Show details of highlighted task"),
			self.SHOW_EVENT_DETAILS: _("Show event details"),
			self.SHOW_NEXT_COMMIT_LOG: _("Show next commit log"),
			self.SHOW_NEXT_PAGE: _("Show next page"),
			self.SHOW_NEXT_PICTURE: _("Show next picture"),
			self.SHOW_NEXT_SERVICE_INFORMATION_SCREEN: _("Show next service information screen"),
			self.SHOW_NEXT_SYSTEM_INFORMATION_SCREEN: _("Show next system information screen"),
			self.SHOW_PREVIOUS_COMMIT_LOG: _("Show previous commit log"),
			self.SHOW_PREVIOUS_PAGE: _("Show previous page"),
			self.SHOW_PREVIOUS_PICTURE: _("Show previous picture"),
			self.SHOW_PREVIOUS_SERVICE_INFORMATION_SCREEN: _("Show previous service information screen"),
			self.SHOW_PREVIOUS_SYSTEM_INFORMATION_SCREEN: _("Show previous system information screen"),
			self.SHOW_THE_INFORMATION_ON_CURRENT_EVENT: _("Open event information"),
			self.START_AN_INSTANT_RECORDING: _("Start an instant recording"),
			self.STOP_THE_UPDATE_IF_RUNNING_THEN_EXIT: _("Stop the update, if running, then exit"),
			self.SWITCH_BETWEEN_FILE_LIST_PLAY_LIST: _("Switch between file list/play list"),
			self.SWITCH_EPG_PAGE_DOWN: _("Switch EPG Page Down"),
			self.SWITCH_EPG_PAGE_UP: _("Switch EPG Page Up"),
			self.SWITCH_TO_HDMI_IN_MODE: _("Switch to HDMI in mode"),
			self.SWITCH_TO_THE_LEFT_COLUMN: _("Switch to the left column"),
			self.SWITCH_TO_THE_RIGHT_COLUMN: _("Switch to the right column"),
			self.TOGGLE_DISPLAY_OF_THE_INFOBAR: _("Cycle through the InfoBars"),
			self.TOGGLE_MOVE_MODE: _("Toggle move mode"),
			self.ZOOM_IN_OUT_TV: _("Zoom In/Out TV"),
			self.ZOOM_OFF: _("Zoom Off")
			# END
		}

		self.commonStrings = {
			"close": self.CLOSE_SCREEN,
			"down": self.MOVE_DOWN_A_LINE,
			"up": self.MOVE_UP_A_LINE,
			"pageDown": self.MOVE_DOWN_A_PAGE,
			"pageUp": self.MOVE_UP_A_PAGE,
			"1": self.NUMBER_OR_SMS_STYLE_DATA_ENTRY,
			"2": self.NUMBER_OR_SMS_STYLE_DATA_ENTRY,
			"3": self.NUMBER_OR_SMS_STYLE_DATA_ENTRY,
			"4": self.NUMBER_OR_SMS_STYLE_DATA_ENTRY,
			"5": self.NUMBER_OR_SMS_STYLE_DATA_ENTRY,
			"6": self.NUMBER_OR_SMS_STYLE_DATA_ENTRY,
			"7": self.NUMBER_OR_SMS_STYLE_DATA_ENTRY,
			"8": self.NUMBER_OR_SMS_STYLE_DATA_ENTRY,
			"9": self.NUMBER_OR_SMS_STYLE_DATA_ENTRY,
			"0": self.NUMBER_OR_SMS_STYLE_DATA_ENTRY
		}

	def getString(self, key):
		return self.strings.get(key, "")

	def getCommonString(self, action):
		return self.strings.get(self.commonStrings.get(action, 0), "")


globalStrings = GlobalStrings()
