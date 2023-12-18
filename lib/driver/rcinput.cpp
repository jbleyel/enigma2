#include <lib/driver/rcinput.h>

#include <lib/base/eerror.h>

#include <sys/ioctl.h>
#include <linux/input.h>
#include <linux/kd.h>
#include <sys/stat.h>
#include <fcntl.h>

#include <lib/base/ebase.h>
#include <lib/base/init.h>
#include <lib/base/init_num.h>
#include <lib/driver/input_fake.h>

static std::unordered_map<int,std::string> value_map {
	{0, "Make"},
	{1, "Break"},
	{2, "Repeat"},
	{3, "Long"},
	{4, "ASCII"}
};

static std::unordered_map<int,std::string> keys_map {
	{0, "KEY_RESERVED"}, 
	{1, "KEY_ESC"}, 
	{2, "KEY_1"}, 
	{3, "KEY_2"}, 
	{4, "KEY_3"}, 
	{5, "KEY_4"}, 
	{6, "KEY_5"}, 
	{7, "KEY_6"}, 
	{8, "KEY_7"}, 
	{9, "KEY_8"}, 
	{10, "KEY_9"}, 
	{11, "KEY_0"}, 
	{12, "KEY_MINUS"}, 
	{13, "KEY_EQUAL"}, 
	{14, "KEY_BACKSPACE"}, 
	{15, "KEY_TAB"}, 
	{16, "KEY_Q"}, 
	{17, "KEY_W"}, 
	{18, "KEY_E"}, 
	{19, "KEY_R"}, 
	{20, "KEY_T"}, 
	{21, "KEY_Y"}, 
	{22, "KEY_U"}, 
	{23, "KEY_I"}, 
	{24, "KEY_O"}, 
	{25, "KEY_P"}, 
	{26, "KEY_LEFTBRACE"}, 
	{27, "KEY_RIGHTBRACE"}, 
	{28, "KEY_ENTER"}, 
	{29, "KEY_LEFTCTRL"}, 
	{30, "KEY_A"}, 
	{31, "KEY_S"}, 
	{32, "KEY_D"}, 
	{33, "KEY_F"}, 
	{34, "KEY_G"}, 
	{35, "KEY_H"}, 
	{36, "KEY_J"}, 
	{37, "KEY_K"}, 
	{38, "KEY_L"}, 
	{39, "KEY_SEMICOLON"}, 
	{40, "KEY_APOSTROPHE"}, 
	{41, "KEY_GRAVE"}, 
	{42, "KEY_LEFTSHIFT"}, 
	{43, "KEY_BACKSLASH"}, 
	{44, "KEY_Z"}, 
	{45, "KEY_X"}, 
	{46, "KEY_C"}, 
	{47, "KEY_V"}, 
	{48, "KEY_B"}, 
	{49, "KEY_N"}, 
	{50, "KEY_M"}, 
	{51, "KEY_COMMA"}, 
	{52, "KEY_DOT"}, 
	{53, "KEY_SLASH"}, 
	{54, "KEY_RIGHTSHIFT"}, 
	{55, "KEY_KPASTERISK"}, 
	{56, "KEY_LEFTALT"}, 
	{57, "KEY_SPACE"}, 
	{58, "KEY_CAPSLOCK"}, 
	{59, "KEY_F1"}, 
	{60, "KEY_F2"}, 
	{61, "KEY_F3"}, 
	{62, "KEY_F4"}, 
	{63, "KEY_F5"}, 
	{64, "KEY_F6"}, 
	{65, "KEY_F7"}, 
	{66, "KEY_F8"}, 
	{67, "KEY_F9"}, 
	{68, "KEY_F10"}, 
	{69, "KEY_NUMLOCK"}, 
	{70, "KEY_SCROLLLOCK"}, 
	{71, "KEY_KP7"}, 
	{72, "KEY_KP8"}, 
	{73, "KEY_KP9"}, 
	{74, "KEY_KPMINUS"}, 
	{75, "KEY_KP4"}, 
	{76, "KEY_KP5"}, 
	{77, "KEY_KP6"}, 
	{78, "KEY_KPPLUS"}, 
	{79, "KEY_KP1"}, 
	{80, "KEY_KP2"}, 
	{81, "KEY_KP3"}, 
	{82, "KEY_KP0"}, 
	{83, "KEY_KPDOT"}, 
	{84, "KEY_103RD"}, 
	{85, "KEY_F13"}, 
	{86, "KEY_102ND"}, 
	{87, "KEY_F11"}, 
	{88, "KEY_F12"}, 
	{89, "KEY_F14"}, 
	{90, "KEY_F15"}, 
	{91, "KEY_F16"}, 
	{92, "KEY_F17"}, 
	{93, "KEY_F18"}, 
	{94, "KEY_F19"}, 
	{95, "KEY_F20"}, 
	{96, "KEY_KPENTER"}, 
	{97, "KEY_RIGHTCTRL"}, 
	{98, "KEY_KPSLASH"}, 
	{99, "KEY_SYSRQ"}, 
	{100, "KEY_RIGHTALT"}, 
	{101, "KEY_LINEFEED"}, 
	{102, "KEY_HOME"}, 
	{103, "KEY_UP"}, 
	{104, "KEY_PAGEUP"}, 
	{105, "KEY_LEFT"}, 
	{106, "KEY_RIGHT"}, 
	{107, "KEY_END"}, 
	{108, "KEY_DOWN"}, 
	{109, "KEY_PAGEDOWN"}, 
	{110, "KEY_INSERT"}, 
	{111, "KEY_DELETE"}, 
	{112, "KEY_MACRO"}, 
	{113, "KEY_MUTE"}, 
	{114, "KEY_VOLUMEDOWN"}, 
	{115, "KEY_VOLUMEUP"}, 
	{116, "KEY_POWER"}, 
	{117, "KEY_KPEQUAL"}, 
	{118, "KEY_KPPLUSMINUS"}, 
	{119, "KEY_PAUSE"}, 
	{120, "KEY_F21"}, 
	{121, "KEY_F22"}, 
	{122, "KEY_F23"}, 
	{123, "KEY_F24"}, 
	{124, "KEY_KPCOMMA"}, 
	{125, "KEY_LEFTMETA"}, 
	{126, "KEY_RIGHTMETA"}, 
	{127, "KEY_COMPOSE"}, 
	{128, "KEY_STOP"}, 
	{129, "KEY_AGAIN"}, 
	{130, "KEY_PROPS"}, 
	{131, "KEY_UNDO"}, 
	{132, "KEY_FRONT"}, 
	{133, "KEY_COPY"}, 
	{134, "KEY_OPEN"}, 
	{135, "KEY_PASTE"}, 
	{136, "KEY_FIND"}, 
	{137, "KEY_CUT"}, 
	{138, "KEY_HELP"}, 
	{139, "KEY_MENU"}, 
	{140, "KEY_CALC"}, 
	{141, "KEY_SETUP"}, 
	{142, "KEY_SLEEP"}, 
	{143, "KEY_WAKEUP"}, 
	{144, "KEY_FILE"}, 
	{145, "KEY_SENDFILE"}, 
	{146, "KEY_DELETEFILE"}, 
	{147, "KEY_XFER"}, 
	{148, "KEY_PROG1"}, 
	{149, "KEY_PROG2"}, 
	{150, "KEY_WWW"}, 
	{151, "KEY_MSDOS"}, 
	{152, "KEY_COFFEE"}, 
	{153, "KEY_DIRECTION"}, 
	{154, "KEY_CYCLEWINDOWS"}, 
	{155, "KEY_MAIL"}, 
	{156, "KEY_BOOKMARKS"}, 
	{157, "KEY_COMPUTER"}, 
	{158, "KEY_BACK"}, 
	{159, "KEY_FORWARD"}, 
	{160, "KEY_CLOSECD"}, 
	{161, "KEY_EJECTCD"}, 
	{162, "KEY_EJECTCLOSECD"}, 
	{163, "KEY_NEXTSONG"}, 
	{164, "KEY_PLAYPAUSE"}, 
	{165, "KEY_PREVIOUSSONG"}, 
	{166, "KEY_STOPCD"}, 
	{167, "KEY_RECORD"}, 
	{168, "KEY_REWIND"}, 
	{169, "KEY_PHONE"}, 
	{170, "KEY_ISO"}, 
	{171, "KEY_CONFIG"}, 
	{172, "KEY_HOMEPAGE"}, 
	{173, "KEY_REFRESH"}, 
	{174, "KEY_EXIT"}, 
	{175, "KEY_MOVE"}, 
	{176, "KEY_EDIT"}, 
	{177, "KEY_SCROLLUP"}, 
	{178, "KEY_SCROLLDOWN"}, 
	{179, "KEY_KPLEFTPAREN"}, 
	{180, "KEY_KPRIGHTPAREN"}, 
	{181, "KEY_INTL1"}, 
	{182, "KEY_INTL2"}, 
	{183, "KEY_INTL3"}, 
	{184, "KEY_INTL4"}, 
	{185, "KEY_INTL5"}, 
	{186, "KEY_INTL6"}, 
	{187, "KEY_INTL7"}, 
	{188, "KEY_INTL8"}, 
	{189, "KEY_INTL9"}, 
	{190, "KEY_LANG1"}, 
	{191, "KEY_LANG2"}, 
	{192, "KEY_LANG3"}, 
	{193, "KEY_LANG4"}, 
	{194, "KEY_LANG5"}, 
	{195, "KEY_LANG6"}, 
	{196, "KEY_LANG7"}, 
	{197, "KEY_LANG8"}, 
	{198, "KEY_LANG9"}, 
	{200, "KEY_PLAYCD"}, 
	{201, "KEY_PAUSECD"}, 
	{202, "KEY_PROG3"}, 
	{203, "KEY_PROG4"}, 
	{205, "KEY_SUSPEND"}, 
	{206, "KEY_CLOSE"}, 
	{207, "KEY_PLAY"}, 
	{208, "KEY_FASTFORWARD"}, 
	{209, "KEY_BASSBOOST"}, 
	{210, "KEY_PRINT"}, 
	{211, "KEY_HP"}, 
	{212, "KEY_CAMERA"}, 
	{213, "KEY_SOUND"}, 
	{214, "KEY_QUESTION"}, 
	{215, "KEY_EMAIL"}, 
	{216, "KEY_CHAT"}, 
	{217, "KEY_SEARCH"}, 
	{218, "KEY_CONNECT"}, 
	{219, "KEY_FINANCE"}, 
	{220, "KEY_SPORT"}, 
	{221, "KEY_SHOP"}, 
	{222, "KEY_ALTERASE"}, 
	{223, "KEY_CANCEL"}, 
	{224, "KEY_BRIGHTNESSDOWN"}, 
	{225, "KEY_BRIGHTNESSUP"}, 
	{226, "KEY_MEDIA"}, 
	{227, "KEY_SWITCHVIDEOMODE"}, 
	{238, "KEY_LAN"}, 
	{240, "KEY_UNKNOWN"}, 
	{256, "BTN_0"}, 
	{257, "BTN_1"}, 
	{304, "BtnA"}, 
	{305, "BtnB"}, 
	{306, "BtnC"}, 
	{307, "BtnX"}, 
	{308, "BtnY"}, 
	{309, "BtnZ"}, 
	{310, "BtnTL"}, 
	{311, "BtnTR"}, 
	{312, "BtnTL2"}, 
	{313, "BtnTR2"}, 
	{314, "BtnSelect"}, 
	{315, "BtnStart"}, 
	{351, "KEY_SHIFT"}, 
	{352, "KEY_OK"}, 
	{353, "KEY_SELECT"}, 
	{354, "KEY_GOTO"}, 
	{355, "KEY_CLEAR"}, 
	{356, "KEY_POWER2"}, 
	{357, "KEY_OPTION"}, 
	{358, "KEY_INFO"}, 
	{359, "KEY_TIME"}, 
	{360, "KEY_VENDOR"}, 
	{361, "KEY_ARCHIVE"}, 
	{362, "KEY_PROGRAM"}, 
	{363, "KEY_CHANNEL"}, 
	{364, "KEY_FAVORITES"}, 
	{365, "KEY_EPG"}, 
	{366, "KEY_PVR"}, 
	{367, "KEY_MHP"}, 
	{368, "KEY_LANGUAGE"}, 
	{369, "KEY_TITLE"}, 
	{370, "KEY_SUBTITLE"}, 
	{371, "KEY_ANGLE"}, 
	{372, "KEY_ZOOM"}, 
	{373, "KEY_MODE"}, 
	{374, "KEY_KEYBOARD"}, 
	{375, "KEY_SCREEN"}, 
	{376, "KEY_PC"}, 
	{377, "KEY_TV"}, 
	{378, "KEY_TV2"}, 
	{379, "KEY_VCR"}, 
	{380, "KEY_VCR2"}, 
	{381, "KEY_SAT"}, 
	{382, "KEY_SAT2"}, 
	{383, "KEY_CD"}, 
	{384, "KEY_TAPE"}, 
	{385, "KEY_RADIO"}, 
	{386, "KEY_TUNER"}, 
	{387, "KEY_PLAYER"}, 
	{388, "KEY_TEXT"}, 
	{389, "KEY_DVD"}, 
	{390, "KEY_AUX"}, 
	{391, "KEY_MP3"}, 
	{392, "KEY_AUDIO"}, 
	{393, "KEY_VIDEO"}, 
	{394, "KEY_DIRECTORY"}, 
	{395, "KEY_LIST"}, 
	{396, "KEY_MEMO"}, 
	{397, "KEY_CALENDAR"}, 
	{398, "KEY_RED"}, 
	{399, "KEY_GREEN"}, 
	{400, "KEY_YELLOW"}, 
	{401, "KEY_BLUE"}, 
	{402, "KEY_CHANNELUP"}, 
	{403, "KEY_CHANNELDOWN"}, 
	{404, "KEY_FIRST"}, 
	{405, "KEY_LAST"}, 
	{406, "KEY_AB"}, 
	{407, "KEY_NEXT"}, 
	{408, "KEY_RESTART"}, 
	{409, "KEY_SLOW"}, 
	{410, "KEY_SHUFFLE"}, 
	{411, "KEY_BREAK"}, 
	{412, "KEY_PREVIOUS"}, 
	{413, "KEY_DIGITS"}, 
	{414, "KEY_TEEN"}, 
	{415, "KEY_TWEN"}, 
	{438, "KEY_CONTEXT_MENU"}, 
	{448, "KEY_DEL_EOL"}, 
	{449, "KEY_DEL_EOS"}, 
	{450, "KEY_INS_LINE"}, 
	{451, "KEY_DEL_LINE"}, 
	{510, "KEY_ASCII"}, 
	{511, "KEY_MAX"}, 
	{530, "KEY_MOUSE"}, 
	{627, "KEY_VOD"}
};


static void Print(struct input_event *ev)
{
	//	# 	__u16 type;             -> EV_REP (0x14)
	//	# 	__u16 code;             -> REP_DELAY (0x00) or REP_PERIOD (0x01)
	//	# 	__s32 value;            -> DEFAULTS: 700(REP_DELAY) or 100(REP_PERIOD)
	std::string _value = "Unknown";
	std::string _key = "Unknown";
    std::unordered_map<int,std::string>::iterator i = value_map.find((int)ev->value);
    if (i != value_map.end())
		_value = i->second;
   	i = keys_map.find((int)ev->code);
    if (i != keys_map.end())
		_key = i->second;

	eDebug("[eRCDeviceInputDev] %s %s", _key.c_str(), _value.c_str());
}

void eRCDeviceInputDev::handleCode(long rccode)
{
	struct input_event *ev = (struct input_event *)rccode;

	if (ev->type != EV_KEY)
		return;

	Print(ev);

	int km = iskeyboard ? input->getKeyboardMode() : eRCInput::kmNone;

	switch (ev->code)
	{
		case KEY_LEFTSHIFT:
		case KEY_RIGHTSHIFT:
			shiftState = ev->value;
			break;
		case KEY_CAPSLOCK:
			if (ev->value == 1)
				capsState = !capsState;
			break;
	}

	if (km == eRCInput::kmAll)
		return;

	if (km == eRCInput::kmAscii)
	{
		bool ignore = false;
		bool ascii = (ev->code > 0 && ev->code < 61);

		switch (ev->code)
		{
			case KEY_LEFTCTRL:
			case KEY_RIGHTCTRL:
			case KEY_LEFTSHIFT:
			case KEY_RIGHTSHIFT:
			case KEY_LEFTALT:
			case KEY_RIGHTALT:
			case KEY_CAPSLOCK:
				ignore = true;
				break;
			case KEY_RESERVED:
			case KEY_ESC:
			case KEY_TAB:
			case KEY_BACKSPACE:
			case KEY_ENTER:
			case KEY_INSERT:
			case KEY_DELETE:
			case KEY_MUTE:
				ascii = false;
			default:
				break;
		}

		if (ignore)
		{
			eDebug("[eRCDeviceInputDev] kmAscii ignore %x %x %x", ev->value, ev->code, ev->type);
			return;
		}

		if (ascii)
		{
			if (ev->value)
			{
				if (consoleFd >= 0)
				{
					struct kbentry ke;
					/* off course caps is not the same as shift, but this will have to do for now */
					ke.kb_table = (shiftState || capsState) ? K_SHIFTTAB : K_NORMTAB;
					ke.kb_index = ev->code;
					::ioctl(consoleFd, KDGKBENT, &ke);
					if (ke.kb_value)
						input->keyPressed(eRCKey(this, ke.kb_value & 0xff, eRCKey::flagAscii)); /* emit */
				}
			}
			eDebug("[eRCDeviceInputDev] kmAscii ascii %x %x %x", ev->value, ev->code, ev->type);
			return;
		}
	}

	if (!remaps.empty())
	{
		std::unordered_map<unsigned int, unsigned int>::iterator i = remaps.find(ev->code);
		if (i != remaps.end())
		{
			eDebug("[eRCDeviceInputDev] map: %u->%u", i->first, i->second);
			ev->code = i->second;
		}
	}
	else
	{
#if KEY_PLAY_ACTUALLY_IS_KEY_PLAYPAUSE
		if (ev->code == KEY_PLAY)
		{
			if ((id == "dreambox advanced remote control (native)")  || (id == "bcm7325 remote control"))
			{
				ev->code = KEY_PLAYPAUSE;
			}
		}
#endif

#if TIVIARRC
	if (ev->code == KEY_EPG) {
		ev->code = KEY_INFO;
	}
	else if (ev->code == KEY_MEDIA) {
		ev->code = KEY_EPG;
	}
	else if (ev->code == KEY_INFO) {
		ev->code = KEY_BACK;
	}
	else if (ev->code == KEY_PREVIOUS) {
		ev->code = KEY_SUBTITLE;
	}
	else if (ev->code == KEY_NEXT) {
		ev->code = KEY_TEXT;
	}
	else if (ev->code == KEY_BACK) {
		ev->code = KEY_MEDIA;
	}
	else if (ev->code == KEY_PLAYPAUSE) {
		ev->code = KEY_PLAY;
	}
	else if (ev->code == KEY_RECORD) {
		ev->code = KEY_PREVIOUS;
	}
	else if (ev->code == KEY_STOP) {
		ev->code = KEY_PAUSE;
	}
	else if (ev->code == KEY_PROGRAM) {
		ev->code = KEY_STOP;
	}
	else if (ev->code == KEY_BOOKMARKS) {
		ev->code = KEY_RECORD;
	}
	else if (ev->code == KEY_SLEEP) {
		ev->code = KEY_NEXT;
	}
	else if (ev->code == KEY_TEXT) {
		ev->code = KEY_PAGEUP;
	}
	else if (ev->code == KEY_SUBTITLE) {
		ev->code = KEY_PAGEDOWN;
	}
	else if (ev->code == KEY_LIST) {
		ev->code = KEY_F3;
	}
	else if (ev->code ==  KEY_RADIO) {
		ev->code =  KEY_MODE;
	}
	else if (ev->code == KEY_AUDIO) {
		ev->code = KEY_TV;
	}
	else if (ev->code == KEY_HELP) {
		ev->code = KEY_SLEEP;
	}
	else if (ev->code == KEY_TV) {
		ev->code = KEY_VMODE;
	}
#endif

#if KEY_F6_TO_KEY_FAVORITES
	if (ev->code == KEY_F6) {
		ev->code = KEY_FAVORITES;
	}
#endif

#if KEY_HELP_TO_KEY_AUDIO
	if (ev->code == KEY_HELP) {
		ev->code = KEY_AUDIO;
	}
#endif


#if KEY_WWW_TO_KEY_FILE
	if (ev->code == KEY_WWW) {
		ev->code = KEY_FILE;
	}
#endif

#if KEY_CONTEXT_MENU_TO_KEY_BACK
	if (ev->code == KEY_CONTEXT_MENU) {
		ev->code = KEY_BACK;
	}
#endif

#if KEY_VIDEO_TO_KEY_ANGLE
	if (ev->code == KEY_VIDEO) {
		ev->code = KEY_ANGLE;
	}
#endif

#if KEY_F7_TO_KEY_MENU
	if (ev->code == KEY_F7) {
		ev->code = KEY_MENU;
	}
#endif

#if KEY_F1_TO_KEY_MEDIA
	if (ev->code == KEY_F1) {
		ev->code = KEY_MEDIA;
	}
#endif

#if KEY_HOME_TO_KEY_INFO
	if (ev->code == KEY_HOME) {
		ev->code = KEY_INFO;
	}
#endif

#if KEY_BACK_TO_KEY_EXIT
	if (ev->code == KEY_BACK) {
		ev->code = KEY_EXIT;
	}
#endif

#if KEY_F2_TO_KEY_EPG
	if (ev->code == KEY_F2) {
		ev->code = KEY_EPG;
	}
#endif

#if KEY_ENTER_TO_KEY_OK
	if (ev->code == KEY_ENTER) {
		ev->code = KEY_OK;
	}
#endif

#if KEY_BOOKMARKS_TO_KEY_MEDIA
	if (ev->code == KEY_BOOKMARKS)
	{
		/* formuler and triplex remote send wrong keycode */
		ev->code = KEY_MEDIA;
	}
#endif

#if KEY_VIDEO_TO_KEY_FAVORITES
	if (ev->code == KEY_VIDEO)
	{
		/* formuler rcu fav key send key_media change this to  KEY_FAVORITES */
		ev->code = KEY_FAVORITES;
	}
#endif

#if KEY_FAV_TO_KEY_PVR
	if (ev->code == KEY_FAVORITES)
	{
		/* tomcat remote dont have a PVR Key. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_PVR;
	}
#endif

#if KEY_LAST_TO_KEY_PVR
	if (ev->code == KEY_LAST)
	{
		/* xwidowx Remote rc has a Funktion key, which sends KEY_LAST events but we need a KEY_PVR. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_PVR;
	}
#endif

#if KEY_LAST_TO_KEY_BACK
	if (ev->code == KEY_LAST)
	{
		/* sf108 Remote rc has a Funktion key, which sends KEY_LAST events but we need a KEY_BACK. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_BACK;
	}
#endif

#if KEY_MEDIA_TO_KEY_LIST
	if (ev->code == KEY_MEDIA)
	{
		/* entwodia Remote rc has a Funktion key, which sends KEY_MEDIA events but we need a KEY_LIST. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_LIST;
	}
#endif

#if KEY_F1_TO_KEY_F2
	if (ev->code == KEY_F1)
	{
		/* ET7X00 Remote rc has a Funktion key, which sends KEY_F1 events but we need a KEY_F2. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_F2;
	}
#endif

#if KEY_INFO_TO_KEY_EPG
	if (ev->code == KEY_INFO)
	{
		/* vu Remote rc has a EPG key, which sends KEY_INFO events but we need a KEY_EPG. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_EPG;
	}
#endif

#if KEY_HELP_TO_KEY_INFO
	if (ev->code == KEY_HELP)
	{
		/* vu Remote rc has a HELP key, which sends KEY_HELP events but we need a KEY_INFO. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_INFO;
	}
#endif

#if KEY_VIDEO_IS_KEY_SCREEN
	if (ev->code == KEY_VIDEO)
	{
		/* Blackbox Remote rc has a KEY_PIP key, which sends KEY_VIDEO events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_SCREEN;
	}
#endif

#if KEY_ARCHIVE_TO_KEY_DIRECTORY
	if (ev->code == KEY_ARCHIVE)
	{
		/* Blackbox Remote rc has a KEY_PLUGIN key, which sends KEY_ARCHIVE events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_DIRECTORY;
	}
#endif

#if KEY_TIME_TO_KEY_SLOW
	if (ev->code == KEY_TIME)
	{
		/* Blackbox Remote rc has a KEY_PLUGIN key, which sends KEY_TIME events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_SLOW;
	}
#endif
	
#if KEY_CONTEXT_MENU_TO_KEY_AUX
	if (ev->code == KEY_CONTEXT_MENU)
	{
		/* Gigablue New Remote rc has a KEY_HDMI-IN, which sends KEY_CONTEXT_MENU events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_AUX;
	}
#endif

#if KEY_F2_TO_KEY_F6
	if (ev->code == KEY_F2)
	{
		/* Gigablue New Remote rc has a KEY_PIP key, which sends KEY_F2 events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_F6;
	}
#endif

#if KEY_F1_TO_KEY_F6
	if (ev->code == KEY_F1)
	{
		ev->code = KEY_F6;
	}
#endif

#if KEY_F2_TO_KEY_AUX
	if (ev->code == KEY_F2)
	{
		ev->code = KEY_AUX;
	}
#endif

#if KEY_F3_TO_KEY_LIST
	if (ev->code == KEY_F3)
	{
		/* Xtrend New Remote rc has a KEY_F3 key, which sends KEY_LIST events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_LIST;
	}
#endif

#if KEY_HOME_TO_KEY_HOMEPAGE
	if (ev->code == KEY_HOME)
	{
		/* DAGS map HOME Key to show MediaPlugin */
		ev->code = KEY_HOMEPAGE;
	}
#endif

#if KEY_MEDIA_TO_KEY_KEY_F2
	if (ev->code == KEY_MEDIA)
	{
		/* DAGS map Media to F2 to show MediaCenter */
		ev->code = KEY_F2;
	}
#endif

#if KEY_TV_TO_KEY_VIDEO
	if (ev->code == KEY_TV)
	{
		/* Venton HD1 rc has a no KEY_VIDEO key, which sends KEY_TV events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_VIDEO;
	}
#endif

#if KEY_BOOKMARKS_TO_KEY_DIRECTORY
	if (ev->code == KEY_BOOKMARKS)
	{
		/* Venton ini2 remote has a KEY_BOOKMARKS key we need KEY_DIRECTORY. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_DIRECTORY;
	}
#endif

#if KEY_MEDIA_TO_KEY_BOOKMARKS
	if (ev->code == KEY_MEDIA)
	{
		/* Venton ini2 remote has a KEY_MEDIA key we need KEY_Bookmark. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_BOOKMARKS;
	}
#endif

#if KEY_MEDIA_TO_KEY_OPEN
	if (ev->code == KEY_MEDIA)
	{
		/* Venton ini2 remote has a KEY_MEDIA key we need KEY_OPEN. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_OPEN;
	}
#endif

#if KEY_SEARCH_TO_KEY_WWW
	if (ev->code == KEY_SEARCH)
	{
		/* Venton rc has a a Key WWW and send KEY_SEARCH. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_WWW;
	}
#endif

#if KEY_POWER2_TO_KEY_WWW
	if (ev->code == KEY_POWER2)
	{
		/* Venton rc has a a Key WWW and send KEY_POWER2. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_WWW;
	}
#endif

#if KEY_DIRECTORY_TO_KEY_FILE
	if (ev->code == KEY_DIRECTORY)
	{
		/* Venton rc has a a KEY_DIRECTORY and send KEY_FILE. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_FILE;
	}
#endif

#if KEY_OPTION_TO_KEY_PC
	if (ev->code == KEY_OPTION)
	{
		/* Venton rc has a a Key LAN and send KEY_OPTION. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_PC;
	}
#endif

#if KEY_VIDEO_TO_KEY_MODE
	if (ev->code == KEY_VIDEO)
	{
		/* Venton rc has a a Key Format and send KEY_Video. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_MODE;
	}
#endif
	

#if KEY_GUIDE_TO_KEY_EPG
	if (ev->code == KEY_HELP)
	{
		/* GB800 rc has a KEY_GUIDE key, which sends KEY_HELP events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_EPG;
	}
#endif

#if KEY_SCREEN_TO_KEY_MODE
	if (ev->code == KEY_SCREEN)
	{
		/* GB800 rc has a KEY_ASPECT key, which sends KEY_SCREEN events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_MODE;
	}
#endif

#if KEY_PLAY_IS_KEY_PLAYPAUSE
	if (ev->code == KEY_PLAY)
	{
		/* sogno rc has a KEY_PLAYPAUSE  key, which sends KEY_PLAY events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_PLAYPAUSE;
	}
#endif

#if KEY_PLAY_ACTUALLY_IS_KEY_PLAYPAUSE
	if (ev->code == KEY_PLAY)
	{
		if ((id == "dreambox advanced remote control (native)")  || (id == "bcm7325 remote control"))
		{
			/* 8k rc has a KEY_PLAYPAUSE key, which sends KEY_PLAY events. Correct this, so we do not have to place hacks in the keymaps. */
			ev->code = KEY_PLAYPAUSE;
		}
	}
#endif

#if KEY_F1_TO_KEY_PC
	if (ev->code == KEY_F1)
	{
		/* Technomate , which sends KEY_F1 events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_PC;
	}
#endif

#if KEY_F5_TO_KEY_ANGLE
	if (ev->code == KEY_F5)
	{
		/* Technomate , which sends KEY_F5 events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_ANGLE;
	}
#endif

#if KEY_DOT_TO_KEY_HOMEPAGE
	if (ev->code == KEY_DOT)
	{
		/* Technomate , which sends KEY_DOT events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_HOMEPAGE;
	}
#endif

#if KEY_ZOOM_TO_KEY_SCREEN
	if (ev->code == KEY_ZOOM)
	{
		/* Venton rc has a a Key LAN and send KEY_OPTION. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_SCREEN;
	}
#endif

#if KEY_LIST_TO_KEY_PVR
	if (ev->code == KEY_LIST)
	{
		/* HDx , which sends KEY_LIST events. Correct this, so we do not have to place hacks in the keymaps. */
		ev->code = KEY_PVR;
	}
#endif

#if KEY_BOOKMARKS_IS_KEY_DIRECTORY
	if (ev->code == KEY_BOOKMARKS)
	{
		/* Beyonwiz U4 RCU workaround to open pluginbrowser */
		ev->code = KEY_DIRECTORY;
	}
#endif

#if KEY_VIDEO_TO_KEY_BOOKMARKS
	if (ev->code == KEY_VIDEO)
	{
		/* Axas Ultra have two keys open Movie folder , use Media key to open MediaPlugin */
		ev->code = KEY_BOOKMARKS;
	}
#endif

	}

	Print(ev);

//	eDebug("[eRCDeviceInputDev] %x %x %x", ev->value, ev->code, ev->type);

	switch (ev->value)
	{
		case 0:
			input->keyPressed(eRCKey(this, ev->code, eRCKey::flagBreak)); /*emit*/
			break;
		case 1:
			input->keyPressed(eRCKey(this, ev->code, 0)); /*emit*/
			break;
		case 2:
			input->keyPressed(eRCKey(this, ev->code, eRCKey::flagRepeat)); /*emit*/
			break;
	}
}

int eRCDeviceInputDev::setKeyMapping(const std::unordered_map<unsigned int, unsigned int>& remaps_p)
{
	remaps = remaps_p;
	return eRCInput::remapOk;
}

eRCDeviceInputDev::eRCDeviceInputDev(eRCInputEventDriver *driver, int consolefd)
	:	eRCDevice(driver->getDeviceName(), driver), iskeyboard(driver->isKeyboard()),
		ismouse(driver->isPointerDevice()),
		consoleFd(consolefd), shiftState(false), capsState(false)
{
	setExclusive(true);
	eDebug("[eRCDeviceInputDev] device \"%s\" is a %s", id.c_str(), iskeyboard ? "keyboard" : (ismouse ? "mouse" : "remotecontrol"));
}

void eRCDeviceInputDev::setExclusive(bool b)
{
	if (!iskeyboard && !ismouse)
		driver->setExclusive(b);
}

const char *eRCDeviceInputDev::getDescription() const
{
	return id.c_str();
}

class eInputDeviceInit
{
	struct element
	{
		public:
			char* filename;
			eRCInputEventDriver* driver;
			eRCDeviceInputDev* device;
			element(const char* fn, eRCInputEventDriver* drv, eRCDeviceInputDev* dev):
				filename(strdup(fn)),
				driver(drv),
				device(dev)
			{
			}
			~element()
			{
				delete device;
				delete driver;
				free(filename);
			}
		private:
			element(const element& other); /* no copy */
	};
	typedef std::vector<element*> itemlist;
	std::vector<element*> items;
	int consoleFd;

public:
	eInputDeviceInit()
	{
#if WORKAROUND_KODI_INPUT
		addAll();
#else
		int i = 0;
		consoleFd = ::open("/dev/tty0", O_RDWR);
		while (1)
		{
			char filename[32];
			sprintf(filename, "/dev/input/event%d", i);
			if (::access(filename, R_OK) < 0)
				break;
			add(filename);
			++i;
		}
		eDebug("[eInputDeviceInit] Found %d input devices.", i);
#endif
	}

	~eInputDeviceInit()
	{
		for (itemlist::iterator it = items.begin(); it != items.end(); ++it)
			delete *it;

		if (consoleFd >= 0)
			::close(consoleFd);
	}

	void add(const char* filename)
	{
		eDebug("[eInputDeviceInit] adding device %s", filename);
		eRCInputEventDriver *p = new eRCInputEventDriver(filename);
		items.push_back(new element(filename, p, new eRCDeviceInputDev(p, consoleFd)));
	}

	void remove(const char* filename)
	{
		for (itemlist::iterator it = items.begin(); it != items.end(); ++it)
		{
			if (strcmp((*it)->filename, filename) == 0)
			{
				delete *it;
				items.erase(it);
				return;
			}
		}
		eDebug("[eInputDeviceInit] Remove '%s', not found", filename);
	}

	void addAll(void)
	{
		int i = 0;
		if (consoleFd < 0)
		{
			consoleFd = ::open("/dev/tty0", O_RDWR);
			printf("consoleFd %d\n", consoleFd);
		}
		while (1)
		{
			char filename[32];
			sprintf(filename, "/dev/input/event%d", i);
			if (::access(filename, R_OK) < 0)
				break;
			add(filename);
			++i;
		}
		eDebug("[eInputDeviceInit] Found %d input devices.", i);
	}

	void removeAll(void)
	{
		[[maybe_unused]] size_t size = items.size();
		for (itemlist::iterator it = items.begin(); it != items.end(); ++it)
		{
			delete *it;
		}
		items.clear();
	}
};

eAutoInitP0<eInputDeviceInit> init_rcinputdev(eAutoInitNumbers::rc+1, "input device driver");

void addInputDevice(const char* filename)
{
	init_rcinputdev->add(filename);
}

void removeInputDevice(const char* filename)
{
	init_rcinputdev->remove(filename);
}

void addAllInputDevices(void)
{
	init_rcinputdev->addAll();
}

void removeAllInputDevices(void)
{
	init_rcinputdev->removeAll();
}
