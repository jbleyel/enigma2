#include <lib/gdi/font.h>
#include <lib/gui/elabel.h>
#include <lib/gui/ewindowstyleskinned.h>

eLabel::eLabel(eWidget* parent, int markedPos) : eWidget(parent), scrollTimer(eTimer::create(eApp)) {
	m_pos = markedPos;
	ePtr<eWindowStyle> style;
	getStyle(style);

	style->getFont(eWindowStyle::fontStatic, m_font);

	/* default to topleft alignment */
	m_valign = alignTop;
	m_halign = alignBidi;

	CONNECT(scrollTimer->timeout, eLabel::updateScrollPosition);
}

int eLabel::event(int event, void* data, void* data2) {
	switch (event) {
		case evtPaint: {
			ePtr<eWindowStyle> style;

			getStyle(style);

			eWidget::event(event, data, data2);

			gPainter& painter = *(gPainter*)data2;

			painter.setFont(m_font);
			style->setStyle(painter, eWindowStyle::styleLabel);

			if (m_have_shadow_color)
				painter.setForegroundColor(m_shadow_color);
			else if (m_have_foreground_color)
				painter.setForegroundColor(m_foreground_color);

			int flags = 0;
			if (m_valign == alignTop)
				flags |= gPainter::RT_VALIGN_TOP;
			else if (m_valign == alignCenter)
				flags |= gPainter::RT_VALIGN_CENTER;
			else if (m_valign == alignBottom)
				flags |= gPainter::RT_VALIGN_BOTTOM;

			if (m_halign == alignLeft)
				flags |= gPainter::RT_HALIGN_LEFT;
			else if (m_halign == alignCenter)
				flags |= gPainter::RT_HALIGN_CENTER;
			else if (m_halign == alignRight)
				flags |= gPainter::RT_HALIGN_RIGHT;
			else if (m_halign == alignBlock)
				flags |= gPainter::RT_HALIGN_BLOCK;

			if (m_wrap == 1)
				flags |= gPainter::RT_WRAP;
			else if (m_wrap == 2)
				flags |= gPainter::RT_ELLIPSIS;

			if (m_underline)
				flags |= gPainter::RT_UNDERLINE;

			if (isGradientSet() || m_blend)
				flags |= gPainter::RT_BLEND;

			int x = m_padding.x();
			int y = m_padding.y();

			int w = m_running_text_direction == SCROLL_LEFT_TO_RIGHT ? m_text_size.width() : size().width() - m_padding.right();
			int h = m_running_text_direction == SCROLL_BOTTOM_TO_TOP ? m_text_size.height() : size().height() - m_padding.bottom();

			auto position = eRect(x, y, w, h);
			if (scrollTimer->isActive() && m_run_once && m_first_run && m_scroll_pos == 0) {
				scrollTimer->stop();
				m_run_text = false;
			}

			if (m_running_text_direction && m_run_text) {
				if (!scrollTimer->isActive()) {
					scrollTimer->start(m_start_delay);
					m_scroll_pos = 0;
				}
				if (m_scroll_pos > (m_running_text_direction == SCROLL_LEFT_TO_RIGHT ? m_text_size.width() : m_text_size.height())) {
					m_scroll_pos = m_running_text_direction == SCROLL_LEFT_TO_RIGHT ? -size().width() : -size().height();
					if (!m_first_run)
						m_first_run = true;
				}
				if (m_running_text_direction == SCROLL_LEFT_TO_RIGHT)
					position.setX(position.x() - m_scroll_pos);
				else if (m_running_text_direction == SCROLL_BOTTOM_TO_TOP)
					position.setY(position.y() - m_scroll_pos);
			}

			/* if we don't have shadow, m_shadow_offset will be 0,0 */
			auto shadowposition = eRect(position.x() - m_shadow_offset.x(), position.y() - m_shadow_offset.y(), position.width() - m_shadow_offset.x(), position.height() - m_shadow_offset.y());
			painter.renderText(shadowposition, m_text, flags, m_text_border_color, m_text_border_width, m_pos, &m_text_offset, m_tab_width);

			if (m_have_shadow_color) {
				if (!m_have_foreground_color)
					style->setStyle(painter, eWindowStyle::styleLabel);
				else
					painter.setForegroundColor(m_foreground_color);

				painter.setBackgroundColor(m_shadow_color);

				painter.renderText(position, m_text, flags, gRGB(), 0, m_pos, &m_text_shaddowoffset, m_tab_width);
			}

			return 0;
		}
		case evtChangedFont:
		case evtChangedText:
		case evtChangedAlignment:
		case evtChangedMarkedPos:
			invalidate();
			return 0;
		case evtParentVisibilityChanged:
			if (!isVisible()) {
				scrollTimer->stop();
				m_first_run = false;
				m_scroll_started = false;
			}
			return 0;
		default:
			return eWidget::event(event, data, data2);
	}
}

void eLabel::setText(const std::string& string) {
	if (m_text == string)
		return;
	m_text = string;
	event(evtChangedText);
}

void eLabel::setMarkedPos(int markedPos) {
	m_pos = markedPos;
	event(evtChangedMarkedPos);
}

void eLabel::setFont(gFont* font) {
	m_font = font;
	event(evtChangedFont);
}

void eLabel::setVAlign(int align) {
	m_valign = align;
	event(evtChangedAlignment);
}

void eLabel::setHAlign(int align) {
	m_halign = align;
	event(evtChangedAlignment);
}

void eLabel::setForegroundColor(const gRGB& col) {
	if ((!m_have_foreground_color) || (m_foreground_color != col)) {
		m_foreground_color = col;
		m_have_foreground_color = 1;
		invalidate();
	}
}

gRGB eLabel::getForegroundColor(int styleID) {
	if (m_have_foreground_color)
		return m_foreground_color;

	ePtr<eWindowStyleManager> mgr;
	eWindowStyleManager::getInstance(mgr);

	if (mgr) {
		ePtr<eWindowStyle> style;
		mgr->getStyle(styleID, style);
		if (style) {
			return style->getColor(eWindowStyleSkinned::colForeground);
		}
	}
	return gRGB(0xFFFFFF);
}

void eLabel::setShadowColor(const gRGB& col) {
	if ((!m_have_shadow_color) || (m_shadow_color != col)) {
		m_shadow_color = col;
		m_have_shadow_color = 1;
		invalidate();
	}
}

void eLabel::setTextBorderColor(const gRGB& col) {
	if (m_text_border_color != col) {
		m_text_border_color = col;
		invalidate();
	}
}

void eLabel::setWrap(int wrap) {
	if (m_wrap != wrap) {
		m_wrap = wrap;
		invalidate();
	}
}

void eLabel::setUnderline(bool underline) {
	if (m_underline != underline) {
		m_underline = underline;
		invalidate();
	}
}

void eLabel::setAlphatest(int alphatest) {
	bool blend = (alphatest > 0); // blend if BT_ALPHATEST or BT_ALPHABLEND
	if (m_blend != blend) {
		m_blend = blend;
		invalidate();
	}
}

void eLabel::clearForegroundColor() {
	if (m_have_foreground_color) {
		m_have_foreground_color = 0;
		invalidate();
	}
}

void eLabel::setTabWidth(int width) {
	if (width == -1) {
		eTextPara para(eRect(0, 0, 1000, 1000));
		para.setFont(m_font);
		para.renderString("W", 0);
		m_tab_width = para.getBoundBox().size().width() * 8;
	} else {
		m_tab_width = width;
	}
}

eSize eLabel::calculateSize() {
	return calculateTextSize(m_font, m_text, size(), m_wrap == 0);
}

eSize eLabel::calculateTextSize(gFont* font, const std::string& string, eSize targetSize, bool nowrap) {
	// Calculate text size for a piece of text without creating an eLabel instance
	// this avoids the side effect of "invalidate" being called on the parent container
	// during the setup of the font and text on the eLabel
	eTextPara para(eRect(0, 0, targetSize.width(), targetSize.height()));
	para.setFont(font);
	para.renderString(string.empty() ? 0 : string.c_str(), nowrap ? 0 : RS_WRAP);
	return para.getBoundBox().size();
}

void eLabel::setScrollText(int direction, long delay, long startDelay, bool runOnce) {
	if (m_running_text_direction == direction || direction == SCROLL_NONE)
		return;
	m_running_text_direction = direction;
	m_run_once = runOnce;
	m_start_delay = startDelay;
	if (m_start_delay > 10000)
		m_start_delay = 10000;
	m_delay = std::max(delay, (long)50); // minimum 50 ms
	m_text_size = calculateTextSize(m_font, m_text, size(), direction == SCROLL_LEFT_TO_RIGHT ? true : false);
	m_run_text = direction == SCROLL_LEFT_TO_RIGHT ? m_text_size.width() > size().width() : m_text_size.height() > size().height();
	eDebug("[eLabel] m_run_text = %d text width=%i text height=%i size width=%i size height=%i", m_run_text, m_text_size.width(), m_text_size.height(), size().width(), size().height());
	if (m_run_text) {
		m_first_run = false;
		m_scroll_started = false;
		invalidate();
	}
}

void eLabel::updateScrollPosition() {
	m_scroll_pos += 2;
	if (!m_scroll_started) {
		m_scroll_started = true;
		scrollTimer->changeInterval(m_delay);
	}
	invalidate();
}
