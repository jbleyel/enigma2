class GlobalStrings():
	ACTIVATE_MAC_ADDRESS_CONFIGURATION = 1
	ACTIVATE_NETWORK_ADAPTER_CONFIGURATION = 2
	ADD_A_NEW_TITLE = 3
	AUDIO_OPTIONS = 4
	CANCEL_ANY_CHANGED_SETTINGS_AND_EXIT = 5
	CANCEL_ANY_CHANGED_SETTINGS_AND_EXIT_ALL_MENUS = 6
	CANCEL_ANY_CHANGED_TAGS_AND_EXIT = 7
	CANCEL_SELECTION = 8
	CANCEL_SERVICE_SELECTION_AND_EXIT = 9
	CANCEL_THE_IMAGE_SELECTION_AND_EXIT = 10
	CANCEL_THE_SELECTION_AND_EXIT = 11
	CHANGE_TO_BOUQUET = 12
	CLOSE_SCREEN = 13
	CLOSE_TASK_LIST = 14
	CLOSE_TASK_VIEW = 15
	CLOSE_THE_CURRENT_SCREEN = 16
	CLOSE_THE_KEXEC_MULTIBOOT_MANAGER = 17
	CLOSE_THE_SCREEN = 18
	CLOSE_THE_SCREEN_AND_EXIT_ALL_MENUS = 19
	CLOSE_THE_WINDOW = 20
	CLOSE_THIS_SCREEN = 21
	CONTINUE_PLAYBACK = 22
	DELETE_ALL_THE_TEXT = 23
	DIGIT_BUTTON = 24
	DIGIT_ENTRY_FOR_SERVICE_SELECTION = 25
	DIRECT_MENU_ITEM_SELECTION = 26
	DISPLAY_MORE_INFORMATION_ABOUT_THIS_FILE = 27
	DISPLAY_SELECTION_LIST_AS_A_SELECTION_MENU = 28
	ENTER_NUMBER_TO_JUMP_TO_CHANNEL = 29
	EXIT_EDITOR_AND_DISCARD_ANY_CHANGES = 30
	EXIT_IMAGE_VIEWER = 31
	EXIT_INPUT_DEVICE_SELECTION = 32
	EXIT_MAC_ADDRESS_CONFIGURATION = 33
	EXIT_MENU = 34
	EXIT_NETWORK_ADAPTER_CONFIGURATION = 35
	EXIT_NETWORK_ADAPTER_SETUP_MENU = 36
	EXIT_NETWORK_INTERFACE_LIST = 37
	EXIT_VIEWER = 38
	FIND_SIMILAR_EVENTS_IN_THE_EPG = 39
	GO_BACK_TO_THE_PREVIOUS_STEP = 40
	JUMP_BACK_ONE_HOUR = 41
	JUMP_FORWARD_ONE_HOUR = 42
	KEYBOARD_DATA_ENTRY = 43
	LEAVE_MOVIE_PLAYER = 44
	LETTERBOX_ZOOM = 45
	LIST_EPG_FUNCTIONS = 46
	MENU = 47
	MOVE_DOWN_A_LINE = 48
	MOVE_DOWN_A_PAGE = 49
	MOVE_DOWN_A_PAGE___SCREEN = 50
	MOVE_DOWN_A_SCREEN = 51
	MOVE_DOWN_TO_LAST_ENTRY = 52
	MOVE_THE_CURRENT_ENTRY_DOWN = 53
	MOVE_THE_CURRENT_ENTRY_UP = 54
	MOVE_TO_FIRST_LINE = 55
	MOVE_TO_FIRST_LINE___SCREEN = 56
	MOVE_TO_LAST_LINE = 57
	MOVE_TO_LAST_LINE___SCREEN = 58
	MOVE_TO_THE_FIRST_ITEM_ON_THE_CURRENT_LINE = 59
	MOVE_TO_THE_FIRST_ITEM_ON_THE_FIRST_SCREEN = 60
	MOVE_TO_THE_FIRST_LINE___SCREEN = 61
	MOVE_TO_THE_LAST_ITEM_ON_THE_CURRENT_LINE = 62
	MOVE_TO_THE_LAST_ITEM_ON_THE_LAST_SCREEN = 63
	MOVE_TO_THE_LAST_LINE___SCREEN = 64
	MOVE_UP_A_LINE = 65
	MOVE_UP_A_PAGE = 66
	MOVE_UP_A_PAGE___SCREEN = 67
	MOVE_UP_A_SCREEN = 68
	MOVE_UP_TO_FIRST_ENTRY = 69
	NUMBER_OR_SMS_STYLE_DATA_ENTRY = 70
	OPEN_THE_MOVIE_LIST = 71
	PAUSE_PLAYBACK = 72
	PLAY_THE_SELECTED_SERVICE = 73
	REFRESH_SCREEN = 74
	REFRESH_THE_SCREEN = 75
	RESET_ENTRIES_TO_THEIR_DEFAULT_VALUES = 76
	RESET_THE_ORDER_OF_THE_ENTRIES = 77
	SAVE_ALL_CHANGED_SETTINGS_AND_EXIT = 78
	SAVE_ALL_CHANGED_TAGS_AND_EXIT = 79
	SEEK = 80
	SEEK_BACKWARD_ENTER_TIME = 81
	SEEK_FORWARD_ENTER_TIME = 82
	SELECT_A_MENU_ITEM = 83
	SELECT_CHANNEL_AUDIO = 84
	SELECT_INPUT_DEVICE = 85
	SELECT_INTERFACE = 86
	SELECT_MENU_ENTRY = 87
	SELECT_QUAD_CHANNELS = 88
	SELECT_SHARES = 89
	SELECT_THE_CURRENTLY_HIGHLIGHTED_SERVICE = 90
	SELECT_THE_HIGHLIGHTED_IMAGE_AND_PROCEED_TO_THE_SLOT_SELECTION = 91
	SELECT_THE_HIGHLIGHTED_SLOT_AND_REBOOT = 92
	SHOW_CHANNEL_SELECTION = 93
	SHOW_DETAILS_OF_HIGHLIGHTED_TASK = 94
	SHOW_EVENT_DETAILS = 95
	SHOW_FIRST_IMAGE = 96
	SHOW_LAST_IMAGE = 97
	SHOW_NEXT_COMMIT_LOG = 98
	SHOW_NEXT_PAGE = 99
	SHOW_NEXT_PICTURE = 100
	SHOW_NEXT_SERVICE_INFORMATION_SCREEN = 101
	SHOW_NEXT_SYSTEM_INFORMATION_SCREEN = 102
	SHOW_PREVIOUS_COMMIT_LOG = 103
	SHOW_PREVIOUS_PAGE = 104
	SHOW_PREVIOUS_PICTURE = 105
	SHOW_PREVIOUS_SERVICE_INFORMATION_SCREEN = 106
	SHOW_PREVIOUS_SYSTEM_INFORMATION_SCREEN = 107
	SHOW_PROGRAM_INFORMATION = 108
	SHOW_QUICKMENU = 109
	SHOW_THE_DREAMPLEX_PLAYER = 110
	SHOW_THE_INFORMATION_ON_CURRENT_EVENT = 111
	SHOW_THE_MEDIA_PLAYER = 112
	SHOW_THE_PLUGIN_BROWSER = 113
	STOP_THE_UPDATE_IF_RUNNING_THEN_EXIT = 114
	SWITCH_BETWEEN_FILE_LIST_PLAY_LIST = 115
	SWITCH_EPG_PAGE_DOWN = 116
	SWITCH_EPG_PAGE_UP = 117
	SWITCH_TO_HDMI_IN_MODE = 118
	SWITCH_TO_THE_LEFT_COLUMN = 119
	SWITCH_TO_THE_RIGHT_COLUMN = 120
	TOGGLE_DISPLAY_OF_IMAGE_INFORMATION = 121
	TOGGLE_DISPLAY_OF_THE_INFOBAR = 122
	TOGGLE_MOVE_MODE = 123

	def __init__(self):
		self.reloadStrings()

	def reloadStrings(self):
		self.strings = {
			self.ACTIVATE_MAC_ADDRESS_CONFIGURATION: _("Activate MAC address configuration"),
			self.ACTIVATE_NETWORK_ADAPTER_CONFIGURATION: _("Activate network adapter configuration"),
			self.ADD_A_NEW_TITLE: _("Add a new title"),
			self.AUDIO_OPTIONS: _("Audio options..."),
			self.CANCEL_ANY_CHANGED_SETTINGS_AND_EXIT: _("Cancel any changed settings and exit"),
			self.CANCEL_ANY_CHANGED_SETTINGS_AND_EXIT_ALL_MENUS: _("Cancel any changed settings and exit all menus"),
			self.CANCEL_ANY_CHANGED_TAGS_AND_EXIT: _("Cancel any changed tags and exit"),
			self.CANCEL_SELECTION: _("Cancel selection"),
			self.CANCEL_SERVICE_SELECTION_AND_EXIT: _("Cancel service selection and exit"),
			self.CANCEL_THE_IMAGE_SELECTION_AND_EXIT: _("Cancel the image selection and exit"),
			self.CANCEL_THE_SELECTION_AND_EXIT: _("Cancel the selection and exit"),
			self.CHANGE_TO_BOUQUET: _("Change to bouquet"),
			self.CLOSE_SCREEN: _("Close screen"),
			self.CLOSE_TASK_LIST: _("Close Task List"),
			self.CLOSE_TASK_VIEW: _("Close Task View"),
			self.CLOSE_THE_CURRENT_SCREEN: _("Close the current screen"),
			self.CLOSE_THE_KEXEC_MULTIBOOT_MANAGER: _("Close the Kexec MultiBoot Manager"),
			self.CLOSE_THE_SCREEN: _("Close the screen"),
			self.CLOSE_THE_SCREEN_AND_EXIT_ALL_MENUS: _("Close the screen and exit all menus"),
			self.CLOSE_THE_WINDOW: _("Close the window"),
			self.CLOSE_THIS_SCREEN: _("Close this screen"),
			self.CONTINUE_PLAYBACK: _("Continue playback"),
			self.DELETE_ALL_THE_TEXT: _("Delete all the text"),
			self.DIGIT_BUTTON: _("DIGIT button"),
			self.DIGIT_ENTRY_FOR_SERVICE_SELECTION: _("Digit entry for service selection"),
			self.DIRECT_MENU_ITEM_SELECTION: _("Direct menu item selection"),
			self.DISPLAY_MORE_INFORMATION_ABOUT_THIS_FILE: _("Display more information about this file"),
			self.DISPLAY_SELECTION_LIST_AS_A_SELECTION_MENU: _("Display selection list as a selection menu"),
			self.ENTER_NUMBER_TO_JUMP_TO_CHANNEL: _("Enter number to jump to channel"),
			self.EXIT_EDITOR_AND_DISCARD_ANY_CHANGES: _("Exit editor and discard any changes"),
			self.EXIT_IMAGE_VIEWER: _("Exit image viewer"),
			self.EXIT_INPUT_DEVICE_SELECTION: _("Exit input device selection."),
			self.EXIT_MAC_ADDRESS_CONFIGURATION: _("Exit MAC address configuration"),
			self.EXIT_MENU: _("Exit menu"),
			self.EXIT_NETWORK_ADAPTER_CONFIGURATION: _("Exit network adapter configuration"),
			self.EXIT_NETWORK_ADAPTER_SETUP_MENU: _("Exit network adapter setup menu"),
			self.EXIT_NETWORK_INTERFACE_LIST: _("Exit network interface list"),
			self.EXIT_VIEWER: _("Exit viewer"),
			self.FIND_SIMILAR_EVENTS_IN_THE_EPG: _("Find similar events in the EPG"),
			self.GO_BACK_TO_THE_PREVIOUS_STEP: _("Go back to the previous step"),
			self.JUMP_BACK_ONE_HOUR: _("Jump back one hour"),
			self.JUMP_FORWARD_ONE_HOUR: _("Jump forward one hour"),
			self.KEYBOARD_DATA_ENTRY: _("Keyboard data entry"),
			self.LEAVE_MOVIE_PLAYER: _("leave movie player"),
			self.LETTERBOX_ZOOM: _("Letterbox zoom"),
			self.LIST_EPG_FUNCTIONS: _("List EPG functions..."),
			self.MENU: _("Menu"),
			self.MOVE_DOWN_A_LINE: _("Move down a line"),
			self.MOVE_DOWN_A_PAGE: _("Move down a page"),
			self.MOVE_DOWN_A_PAGE___SCREEN: _("Move down a page / screen"),
			self.MOVE_DOWN_A_SCREEN: _("Move down a screen"),
			self.MOVE_DOWN_TO_LAST_ENTRY: _("Move down to last entry"),
			self.MOVE_THE_CURRENT_ENTRY_DOWN: _("Move the current entry down"),
			self.MOVE_THE_CURRENT_ENTRY_UP: _("Move the current entry up"),
			self.MOVE_TO_FIRST_LINE: _("Move to first line"),
			self.MOVE_TO_FIRST_LINE___SCREEN: _("Move to first line / screen"),
			self.MOVE_TO_LAST_LINE: _("Move to last line"),
			self.MOVE_TO_LAST_LINE___SCREEN: _("Move to last line / screen"),
			self.MOVE_TO_THE_FIRST_ITEM_ON_THE_CURRENT_LINE: _("Move to the first item on the current line"),
			self.MOVE_TO_THE_FIRST_ITEM_ON_THE_FIRST_SCREEN: _("Move to the first item on the first screen"),
			self.MOVE_TO_THE_FIRST_LINE___SCREEN: _("Move to the first line / screen"),
			self.MOVE_TO_THE_LAST_ITEM_ON_THE_CURRENT_LINE: _("Move to the last item on the current line"),
			self.MOVE_TO_THE_LAST_ITEM_ON_THE_LAST_SCREEN: _("Move to the last item on the last screen"),
			self.MOVE_TO_THE_LAST_LINE___SCREEN: _("Move to the last line / screen"),
			self.MOVE_UP_A_LINE: _("Move up a line"),
			self.MOVE_UP_A_PAGE: _("Move up a page"),
			self.MOVE_UP_A_PAGE___SCREEN: _("Move up a page / screen"),
			self.MOVE_UP_A_SCREEN: _("Move up a screen"),
			self.MOVE_UP_TO_FIRST_ENTRY: _("Move up to first entry"),
			self.NUMBER_OR_SMS_STYLE_DATA_ENTRY: _("Number or SMS style data entry"),
			self.OPEN_THE_MOVIE_LIST: _("Open the movie list"),
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
			self.SHOW_FIRST_IMAGE: _("Show first image"),
			self.SHOW_LAST_IMAGE: _("Show last image"),
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
			self.SHOW_PROGRAM_INFORMATION: _("show program information..."),
			self.SHOW_QUICKMENU: _("Show quickmenu..."),
			self.SHOW_THE_DREAMPLEX_PLAYER: _("Show the DreamPlex player..."),
			self.SHOW_THE_INFORMATION_ON_CURRENT_EVENT: _("Show the information on current event."),
			self.SHOW_THE_MEDIA_PLAYER: _("Show the media player..."),
			self.SHOW_THE_PLUGIN_BROWSER: _("Show the plugin browser.."),
			self.STOP_THE_UPDATE_IF_RUNNING_THEN_EXIT: _("Stop the update, if running, then exit"),
			self.SWITCH_BETWEEN_FILE_LIST_PLAY_LIST: _("Switch between file list/play list"),
			self.SWITCH_EPG_PAGE_DOWN: _("Switch EPG Page Down"),
			self.SWITCH_EPG_PAGE_UP: _("Switch EPG Page Up"),
			self.SWITCH_TO_HDMI_IN_MODE: _("Switch to HDMI in mode"),
			self.SWITCH_TO_THE_LEFT_COLUMN: _("Switch to the left column"),
			self.SWITCH_TO_THE_RIGHT_COLUMN: _("Switch to the right column"),
			self.TOGGLE_DISPLAY_OF_IMAGE_INFORMATION: _("Toggle display of image information"),
			self.TOGGLE_DISPLAY_OF_THE_INFOBAR: _("Toggle display of the InfoBar"),
			self.TOGGLE_MOVE_MODE: _("Toggle move mode")
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
