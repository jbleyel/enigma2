#ifndef __lib_gui_elabel_h
#define __lib_gui_elabel_h

#include <lib/gui/ewidget.h>

class eLabel : public eWidget {
public:
	eLabel(eWidget* parent, int markedPos = -1);
	void setText(const std::string& string);
	void setMarkedPos(int markedPos);
	void setFont(gFont* font);
	gFont* getFont() {
		return m_font;
	}

	enum { alignLeft, alignTop = alignLeft, alignCenter, alignRight, alignBottom = alignRight, alignBlock, alignBidi };

	enum { SCROLL_NONE, SCROLL_LEFT_TO_RIGHT, SCROLL_BOTTOM_TO_TOP };

	void setVAlign(int align);
	void setHAlign(int align);

	void setForegroundColor(const gRGB& col);
	void setShadowColor(const gRGB& col);
	void setShadowOffset(const ePoint& offset) {
		m_shadow_offset = offset;
	}
	void setBorderColor(const gRGB& col) override {
		setTextBorderColor(col);
	} // WILL BE CHANGED !!!!
	void setBorderWidth(int width) override {
		setTextBorderWidth(width);
	} // WILL BE CHANGED !!!!
	void setTextBorderColor(const gRGB& col);
	void setTextBorderWidth(int width) {
		m_text_border_width = width;
	}
	void setWrap(int wrap);
	void setNoWrap(int nowrap) {
		setWrap((nowrap == 1) ? 0 : 1);
	} // DEPRECATED
	void setUnderline(bool underline);
	void setScrollText(int direction, long delay, long startDelay, bool runOnce = false);
	void clearForegroundColor();
	int getWrap() const {
		return m_wrap;
	}
	int getNoWrap() const {
		return (m_wrap == 0) ? 1 : 0;
	} // DEPRECATED
	void setAlphatest(int alphatest);
	void setTabWidth(int width);
	gRGB getForegroundColor(int styleID = 0);
	eSize calculateSize();
	static eSize calculateTextSize(gFont* font, const std::string& string, eSize targetSize, bool nowrap = false);

protected:
	ePtr<gFont> m_font;
	int m_valign, m_halign;
	std::string m_text;
	int event(int event, void* data = 0, void* data2 = 0);
	int m_pos;
	int m_text_offset = 0;
	int m_text_shaddowoffset = 0;

private:
	int m_have_foreground_color = 0;
	int m_have_shadow_color = 0;
	gRGB m_foreground_color, m_shadow_color, m_text_border_color;
	ePoint m_shadow_offset;
	int m_text_border_width = 0;
	int m_wrap = 1;
	bool m_blend = false;
	bool m_underline = false;
	int m_tab_width = -1;
	// Scroll
	bool m_first_run = false;
	bool m_run_once = false;
	int m_running_text_direction = SCROLL_NONE;
	bool m_run_text = false;
	bool m_scroll_started = false;
	int m_scroll_pos = 0;
	int m_start_delay = 0;
	int m_delay = 0;
	eSize m_text_size;
	ePtr<eTimer> scrollTimer;
	void updateScrollPosition();

	enum eLabelEvent { evtChangedText = evtUserWidget, evtChangedFont, evtChangedAlignment, evtChangedMarkedPos };

};

#endif
