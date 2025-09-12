#include <lib/gui/estack.h>

eStack::eStack(eWidget* parent, LayoutDirection dir) : eWidget(parent), m_direction(dir) {}

void eStack::setLayoutDirection(LayoutDirection dir) {
	m_direction = dir;
	recalcLayout();
}

void eStack::addChild(eWidget* child) {
	if (!child)
		return;

	child->setStack(this);
	m_stackchilds.push_back(child);
	recalcLayout();
}

void eStack::removeChild(eWidget* child) {
	if (!child)
		return;

	auto it = std::find(m_stackchilds.begin(), m_stackchilds.end(), child);
	if (it != m_stackchilds.end())
		m_stackchilds.erase(it);

	recalcLayout();
}

void eStack::invalidateChilds() {
	eDebug("[eStack] invalidateChilds");
	recalcLayout();
}


int eStack::event(int event, void* data, void* data2) {
	eDebug("[eStack] event %d", event);

	if (event == evtPaint)
		return 0;

	return eWidget::event(event, data, data2);
}

void eStack::recalcLayout() {
	int stack_w = size().width();
	int stack_h = size().height();

	if (stack_w < 0 || stack_h < 0)
		return;

	int x = 0, y = 0;
	int xr = stack_w;
	int yb = stack_h;

	for (auto child : m_stackchilds) {
		if (!child->isVisible())
			continue;

		eSize csize = child->size();
		int cx = 0, cy = 0;
		int cw = csize.width();
		int ch = csize.height();
		int align = child->align();
		if (align == 0)
			continue;

		if (m_direction == Horizontal) {
			cy = child->position().y();
			if (child->align() & eStackAlignLeft) {
				cx = x;
				x += cw;
			} else if (child->align() & eStackAlignRight) {
				cx = xr - cw;
				xr -= cx;
			} else if (child->align() & eStackAlignCenter)
				cx = (stack_w - cw) / 2;

			child->move(ePoint(cx, cy));
		} else {
			cx = child->position().x();
			if (child->align() & eStackAlignTop) {
				cy = y;
				y += cy;
			} else if (child->align() & eStackAlignBottom) {
				cy = yb - ch;
				yb -= cy;
			} else if (child->align() & eStackAlignCenter)
				cy = (stack_h - ch) / 2;

			child->move(ePoint(cx, cy));
		}
	}
}
