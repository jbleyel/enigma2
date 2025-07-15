#include <lib/base/wrappers.h>
#include <lib/gui/epixmap.h>
#include <lib/gdi/epng.h>
#include <lib/gui/ewidgetdesktop.h>

extern "C" {
#include <gif_lib.h>
}

ePixmap::ePixmap(eWidget *parent)
	: eWidget(parent), m_alphatest(0), m_scale(0), m_animTimer(eTimer::create(eApp))
{
	CONNECT(m_animTimer->timeout, ePixmap::nextFrame);
}

ePixmap::~ePixmap()
{
    m_animTimer->stop();
	/*
    for (auto &pix : m_frames) {
        if (pix && pix->surface && pix->surface->clut.data) {
            delete[] pix->surface->clut.data;
            pix->surface->clut.data = nullptr;
        }
    }
	*/
    m_frames.clear();
    m_delays.clear();
}

void ePixmap::setAlphatest(int alphatest)
{
	m_alphatest = alphatest;
	setTransparent(alphatest);
}

void ePixmap::setScale(int scale)
{
	// support old python code beacause the old code will only support BT_SCALE
	scale = (scale) ? gPainter::BT_SCALE : 0;

	if (m_scale != scale)
	{
		m_scale = scale;
		invalidate();
	}
}

void ePixmap::setPixmapScale(int flags)
{
	if (m_scale != flags)
	{
		m_scale = flags;
		invalidate();
	}
}

void ePixmap::setPixmap(gPixmap *pixmap)
{
    m_animTimer->stop();
	m_pixmap = pixmap;
	event(evtChangedPixmap);
}

void ePixmap::setPixmap(ePtr<gPixmap> &pixmap)
{
    m_animTimer->stop();
	m_pixmap = pixmap;
	event(evtChangedPixmap);
}

void ePixmap::setPixmapFromFile(const char *filename)
{
	loadImage(m_pixmap, filename, m_scale, m_scale ? size().width() : 0, m_scale ? size().height() : 0);

	if (!m_pixmap)
	{
		eDebug("[ePixmap] setPixmapFromFile: load %s failed", filename);
		return;
	}

	// TODO: This only works for desktop 0
	getDesktop(0)->makeCompatiblePixmap(*m_pixmap);
	event(evtChangedPixmap);
}

void ePixmap::checkSize()
{
	/* when we have no pixmap, or a pixmap of different size, we need
	   to enable transparency in any case. */
	if (m_pixmap && m_pixmap->size() == size() && !m_alphatest)
		setTransparent(0);
	else
		setTransparent(1);
	/* fall trough. */
}

int ePixmap::event(int event, void *data, void *data2)
{
	switch (event)
	{
	case evtPaint:
	{
		ePtr<eWindowStyle> style;

		eSize s(size());
		getStyle(style);

		//	we don't clear the background before because of performance reasons.
		//	when the pixmap is too small to fit the whole widget area, the widget is
		//	transparent anyway, so the background is already painted.
		//		eWidget::event(event, data, data2);

		gPainter &painter = *(gPainter *)data2;
		int cornerRadius = getCornerRadius();
		if (m_pixmap)
		{
			int flags = 0;
			if (m_alphatest == 1)
				flags = gPainter::BT_ALPHATEST;
			else if (m_alphatest == 2)
				flags = gPainter::BT_ALPHABLEND;

			flags |= m_scale;
			painter.setRadius(cornerRadius, getCornerRadiusEdges());
			painter.blit(m_pixmap, eRect(ePoint(0, 0), s), eRect(), flags);
		}

		if(cornerRadius)
			return 0; // border not suppored for rounded edges

		if (m_have_border_color)
			painter.setForegroundColor(m_border_color);

		if (m_border_width)
		{
			painter.fill(eRect(0, 0, s.width(), m_border_width));
			painter.fill(eRect(0, m_border_width, m_border_width, s.height() - m_border_width));
			painter.fill(eRect(m_border_width, s.height() - m_border_width, s.width() - m_border_width, m_border_width));
			painter.fill(eRect(s.width() - m_border_width, m_border_width, m_border_width, s.height() - m_border_width));
		}
		return 0;
	}
	case evtChangedPixmap:
		checkSize();
		invalidate();
		return 0;
	case evtChangedSize:
		checkSize();
		[[fallthrough]];
	default:
		return eWidget::event(event, data, data2);
	}
}

void ePixmap::setAniPixmapFromFile(const char *filename, bool autostart)
{
    std::vector<ePtr<gPixmap>> frames;
    std::vector<int> delays;

    int error = 0;
    GifFileType *gif = DGifOpenFileName(filename, &error);
    if (!gif)
        return;

    GifRecordType recordType;
    int delay = 10; // Default delay (0.1s)
    GifByteType *extension = nullptr;
    int extCode = 0;

    do {
        if (DGifGetRecordType(gif, &recordType) == GIF_ERROR)
            break;

        switch (recordType) {
        case IMAGE_DESC_RECORD_TYPE: {
            if (DGifGetImageDesc(gif) == GIF_ERROR)
                break;
            int w = gif->Image.Width;
            int h = gif->Image.Height;
            ePtr<gPixmap> pix(new gPixmap(w, h, 8, nullptr, gPixmap::accelAlways));
            unsigned char *buffer = new unsigned char[w * h];
            unsigned char *row = buffer;

            ColorMapObject *cmap = gif->Image.ColorMap ? gif->Image.ColorMap : gif->SColorMap;
            pix->surface->clut.colors = cmap->ColorCount;
            pix->surface->clut.data = new gRGB[cmap->ColorCount];
            for (int i = 0; i < cmap->ColorCount; ++i) {
                pix->surface->clut.data[i].r = cmap->Colors[i].Red;
                pix->surface->clut.data[i].g = cmap->Colors[i].Green;
                pix->surface->clut.data[i].b = cmap->Colors[i].Blue;
                pix->surface->clut.data[i].a = 0;
            }

            if (!gif->Image.Interlace) {
                for (int y = 0; y < h; ++y) {
                    if (DGifGetLine(gif, row, w) == GIF_ERROR)
                        break;
                    row += w;
                }
            } else {
                static const int IOffset[] = {0, 4, 2, 1};
                static const int IJumps[] = {8, 8, 4, 2};
                for (int j = 0; j < 4; ++j)
                    for (int y = IOffset[j]; y < h; y += IJumps[j])
                        DGifGetLine(gif, buffer + y * w, w);
            }

            memcpy(pix->surface->data, buffer, w * h);
            delete[] buffer;

            frames.push_back(pix);
            delays.push_back(delay * 10); // ms

            delay = 10; // Reset for next frame
            break;
        }
        case EXTENSION_RECORD_TYPE: {
            if (DGifGetExtension(gif, &extCode, &extension) == GIF_ERROR)
                break;
            if (extCode == GRAPHICS_EXT_FUNC_CODE && extension != nullptr)
                delay = extension[2] << 8 | extension[1];
            while (extension != nullptr)
                if (DGifGetExtensionNext(gif, &extension) == GIF_ERROR)
                    break;
            break;
        }
        default:
            break;
        }
    } while (recordType != TERMINATE_RECORD_TYPE);

    DGifCloseFile(gif, &error);

    m_frames = frames;
    m_delays = delays;
    m_currentFrame = 0;
	if( autostart )
	{
		if (!m_frames.empty()) {
			m_pixmap = m_frames[0];
			event(evtChangedPixmap);
			if (m_frames.size() > 1)
				startAnimation();
		}
	}
	
}

void ePixmap::startAnimation(bool once)
{
    m_animTimer->stop();
    if (m_frames.size() > 1 && m_delays.size() == m_frames.size()) {
        m_animTimer->start(m_delays[m_currentFrame], true);
    }
}

void ePixmap::nextFrame()
{
    m_currentFrame = (m_currentFrame + 1) % m_frames.size();
	m_pixmap = m_frames[m_currentFrame];
	event(evtChangedPixmap);
    m_animTimer->start(m_delays[m_currentFrame], true);
}
