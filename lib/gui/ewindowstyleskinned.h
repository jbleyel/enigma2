#ifndef __lib_gui_ewindowstyleskinned_h
#define __lib_gui_ewindowstyleskinned_h

#include <lib/gui/ewindowstyle.h>

class eWindowStyleSkinned: public eWindowStyle
{
	DECLARE_REF(eWindowStyleSkinned);
public:
	eWindowStyleSkinned();
#ifndef SWIG
	void handleNewSize(eWindow *wnd, eSize &size, eSize &offset);
	void paintWindowDecoration(eWindow *wnd, gPainter &painter, const std::string &title);
	void paintBackground(gPainter &painter, const ePoint &offset, const eSize &size);
	void drawFrame(gPainter &painter, const eRect &frame, int what);
	RESULT getFont(int what, ePtr<gFont> &font);
#endif
	void setStyle(gPainter &painter, int what);

	enum {
		bsWindow,
		bsButton,
		bsListboxEntry,
#ifndef SWIG
		bsMax
#endif
	};

	enum {
		bpTopLeft     =     1,
		bpTop         =     2,
		bpTopRight    =     4,
		bpLeft        =     8,
		bpBackground  =  0x10,
		bpRight       =  0x20,
		bpBottomLeft  =  0x40,
		bpBottom      =  0x80,
		bpBottomRight = 0x100,
		bpAll         = 0x1ff,
		bpMax         = 0x200
	};

	enum {
		bpiTopLeft     =  0,
		bpiTop         =  1,
		bpiTopRight    =  2,
		bpiLeft        =  3,
		bpiBackground  =  4,
		bpiRight       =  5,
		bpiBottomLeft  =  6,
		bpiBottom      =  7,
		bpiBottomRight =  8,
	};

	void setPixmap(int bs, int bp, ePtr<gPixmap> &pixmap);
	void setPixmap(int bs, int bp, gPixmap &pixmap);

	enum {
		colBackground,
		colForeground,
		colListboxBackground,
		colListboxForeground,
		colListboxBackgroundSelected,
		colListboxForegroundSelected,
		colListboxBackgroundMarked,
		colListboxForegroundMarked,
		colListboxBackgroundMarkedSelected,
		colListboxForegroundMarkedSelected,

		colWindowTitleForeground,
		colWindowTitleBackground,

		colScrollbarForeground,
		colScrollbarBackground,
		colScrollbarBorder,

		colSliderForeground,
		colSliderBackground,
		colSliderBorder,

		colMax
	};

	enum {
		valueEntryLeftOffset,
		valueHeaderLeftOffset,
		valueIndentSize,
		valueMax
	};
	void setColor(int what, const gRGB &back);
	gRGB getColor(int what);

	void setTitleOffset(const eSize &offset);
	void setTitleFont(gFont *fnt);
	void setLabelFont(gFont *fnt);
	void setListboxFont(gFont *fnt);
	void setEntryFont(gFont *fnt);
	void setValueFont(gFont *fnt);
	void setHeaderFont(gFont *fnt);
	void setValue(int what, int value);
	int getValue(int what);

private:
	struct borderSet
	{
		ePtr<gPixmap> m_pixmap[9];
		int m_border_top, m_border_left, m_border_right, m_border_bottom;
		borderSet() { m_border_top = m_border_left = m_border_right = m_border_bottom = 0; }
	};

	borderSet m_border[bsMax];

	gRGB m_color[colMax];

	eSize m_title_offset;
	ePtr<gFont> m_fnt, m_labelfnt, m_listboxfnt, m_entryfnt, m_valuefnt, m_headerfnt;

	int m_values[valueMax] = {15, 15};

	void drawBorder(gPainter &painter, const eRect &size, struct borderSet &border, int where, int flags);
};

#endif
