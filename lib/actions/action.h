#ifndef __lib_driver_action_h
#define __lib_driver_action_h

#include <lib/base/object.h>
#include <lib/gui/ewidget.h>

#include <lib/python/python.h>
#include <string>
#include <map>
#include <vector>

SWIG_IGNORE(eActionMap);
class eActionMap: public iObject
{
	DECLARE_REF(eActionMap);
#ifdef SWIG
	eActionMap();
	~eActionMap();
#endif
public:
#ifndef SWIG
	eActionMap();
	~eActionMap();
	void bindAction(const std::string &context, int64_t priority, int id, eWidget *widget);
	void unbindAction(eWidget *widget, int id);
#endif

	void bindAction(const std::string &context, int64_t priority, SWIG_PYOBJECT(ePyObject) function);
	void unbindAction(const std::string &context, SWIG_PYOBJECT(ePyObject) function);

	void bindKey(const std::string &domain, const std::string &device, int key, int flags, const std::string &context, const std::string &action);
	void bindTranslation(const std::string &domain, const std::string &device, int keyin, int keyout, int toggle);
	void bindToggle(const std::string &domain, const std::string &device, int togglekey);
	void unbindNativeKey(const std::string &context, int action);
	void unbindPythonKey(const std::string &context, int key, const std::string &action);
	void unbindKeyDomain(const std::string &domain);

	void keyPressed(const std::string &device, int key, int flags);
	void setLongPressedEmulationKey(int key) { m_long_press_emulation_key = key; }

#ifndef SWIG
	static RESULT getInstance(ePtr<eActionMap> &);
	int getLongPressedEmulationKey() const { return m_long_press_emulation_key; }
private:
	static eActionMap *instance;
	int m_long_press_emulation_key = 0;
	struct eActionBinding
	{
		eActionBinding()
			:m_prev_seen_make_key(-1), m_long_key_pressed(false)
		{}
//		eActionContext *m_context;
		std::string m_context; // FIXME
		std::string m_domain;

		ePyObject m_fnc;

		eWidget *m_widget;
		int m_id;
		int m_prev_seen_make_key;
		bool m_long_key_pressed;
	};

	std::multimap<int64_t, eActionBinding> m_bindings;

	struct eTranslationBinding
	{
		int m_keyin;
		int m_keyout;
		int m_toggle;
		std::string m_domain;
	};
	struct eDeviceBinding
	{
		int m_togglekey;
		int m_toggle;
		std::vector<eTranslationBinding> m_translations;
	};
	std::map <std::string, eDeviceBinding> m_rcDevices;

	friend struct compare_string_keybind_native;
	struct eNativeKeyBinding
	{
		std::string m_device;
		std::string m_domain;
		int m_key;
		int m_flags;

//		eActionContext *m_context;
		int m_action;
	};

	std::multimap<std::string, eNativeKeyBinding> m_native_keys;

	friend struct compare_string_keybind_python;
	struct ePythonKeyBinding
	{
		std::string m_device;
		std::string m_domain;
		int m_key;
		int m_flags;

		std::string m_action;
	};

	std::multimap<std::string, ePythonKeyBinding> m_python_keys;
#endif
};
SWIG_TEMPLATE_TYPEDEF(ePtr<eActionMap>, eActionMap);
SWIG_EXTEND(ePtr<eActionMap>,
	static ePtr<eActionMap> getInstance()
	{
		extern ePtr<eActionMap> NewActionMapPtr(void);
		return NewActionMapPtr();
	}
);

#endif
