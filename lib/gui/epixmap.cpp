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

    int width  = gif->SWidth;
    int height = gif->SHeight;

    ColorMapObject *globalColorMap = gif->SColorMap;

    GifRecordType recordType;
    int delay = 100; // Default delay (1/100 sec)

    int disposal = 0;
    int transparent = -1;
    bool has_transparency = false;

    // Canvas für zusammengesetzte Frames (Indexwerte ins Colormap)
    std::vector<unsigned char> canvas(width * height, 0);

    // Backup-Buffer für Disposal=3
    std::vector<unsigned char> prevBuffer(width * height, 0);

    do {
        if (DGifGetRecordType(gif, &recordType) == GIF_ERROR)
            break;

        switch (recordType) {
        case EXTENSION_RECORD_TYPE: {
            int extCode;
            GifByteType *extension;
            if (DGifGetExtension(gif, &extCode, &extension) == GIF_ERROR)
                break;

            if (extCode == GRAPHICS_EXT_FUNC_CODE && extension != nullptr) {
                int blockSize = extension[0];
                if (blockSize >= 4) {

                    unsigned char packed = extension[1];
                    int delay_cs = extension[2] | (extension[3] << 8); // in 1/100s
                    int local_transparent = (packed & 0x01) ? extension[4] : -1;

                    disposal = (packed >> 2) & 0x07;
                    has_transparency = (packed & 0x01) != 0;
                    transparent = local_transparent;
                    delay = (delay_cs > 0) ? delay_cs * 10 : 100; // ms
                }
            }

            while (extension != nullptr) {
                if (DGifGetExtensionNext(gif, &extension) == GIF_ERROR)
                    break;
            }
            break;
        }

        case IMAGE_DESC_RECORD_TYPE: {
            if (DGifGetImageDesc(gif) == GIF_ERROR)
                break;

            int left   = gif->Image.Left;
            int top    = gif->Image.Top;
            int fw     = gif->Image.Width;
            int fh     = gif->Image.Height;

            // Vorherigen Frame sichern falls Disposal=3
            if (disposal == 3)
                prevBuffer = canvas;

            // Disposal anwenden
            if (disposal == 2) {
                // Hintergrund löschen (0 setzen)
                for (int y = 0; y < fh; y++) {
                    int cy = top + y;
                    if (cy >= height) continue;
                    for (int x = 0; x < fw; x++) {
                        int cx = left + x;
                        if (cx < width)
                            canvas[cy * width + cx] = 0;
                    }
                }
            }
            else if (disposal == 3) {
                canvas = prevBuffer;
            }
            // Disposal=0/1: nichts tun

            // Lokale oder globale Palette
            ColorMapObject *colorMap = gif->Image.ColorMap ? gif->Image.ColorMap : globalColorMap;

            // Frame-Daten lesen
            std::vector<unsigned char> buffer(fw * fh);
            for (int y = 0; y < fh; y++) {
                if (DGifGetLine(gif, buffer.data() + y * fw, fw) == GIF_ERROR)
                    break;
            }

            // In Canvas übertragen
            for (int y = 0; y < fh; y++) {
                int cy = top + y;
                if (cy >= height) continue;
                for (int x = 0; x < fw; x++) {
                    int cx = left + x;
                    if (cx >= width) continue;
                    unsigned char pixel = buffer[y * fw + x];
                    if (pixel == transparent)
                        continue; // Skip transparent pixel
                    canvas[cy * width + cx] = pixel;
                }
            }

            // Neues gPixmap mit 32 Bit BGRA
            ePtr<gPixmap> pix = new gPixmap(width, height, 32, nullptr, gPixmap::accelAlways);
            uint32_t* pixdata = static_cast<uint32_t*>(pix->surface->data);

            // Canvas (Indexwerte) -> echte BGRA-Farben
            for (int y = 0; y < height; ++y) {
                for (int x = 0; x < width; ++x) {
                    int idx = canvas[y * width + x];
                    uint32_t outPixel = 0x00000000u; // default transparent black

                    if (idx >= 0 && colorMap && idx < colorMap->ColorCount) {
                        GifColorType c = colorMap->Colors[idx];
                        bool pixelIsTransparent = (has_transparency && idx == transparent);

                        uint8_t A = pixelIsTransparent ? 0x00 : 0xFF;
                        uint8_t R = c.Red;
                        uint8_t G = c.Green;
                        uint8_t B = c.Blue;

                        // BGRA (niedrigstes Byte = B)
                        outPixel = (static_cast<uint32_t>(B)      ) |
                                   (static_cast<uint32_t>(G) << 8 ) |
                                   (static_cast<uint32_t>(R) << 16) |
                                   (static_cast<uint32_t>(A) << 24);
                    }

                    pixdata[y * (pix->surface->stride / 4) + x] = outPixel;
                }
            }

            frames.push_back(pix);
            delays.push_back(delay);

            eDebug("[ePixmap] frame: %d delay=%d disposal=%d transparent=%d hasTransparency=%d left=%d top=%d w=%d h=%d", 
                (int)frames.size() - 1, delay, disposal, transparent, has_transparency,
                left, top, fw, fh);

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

    if (autostart && !m_frames.empty()) {
        m_pixmap = m_frames[0];
        event(evtChangedPixmap);
        if (m_frames.size() > 1)
            startAnimation();
    }
}



/*
void ePixmap::setAniPixmapFromFile(const char *filename, bool autostart)
{
    std::vector<ePtr<gPixmap>> frames;
    std::vector<int> delays;

    int error = 0;
    GifFileType *gif = DGifOpenFileName(filename, &error);
    if (!gif)
        return;

    int width  = gif->SWidth;
    int height = gif->SHeight;

    ColorMapObject *globalColorMap = gif->SColorMap;

    GifRecordType recordType;
    int delay = 100; // Default delay (1/100 sec)

    int disposal = 0;
    int transparent = -1;
    bool has_transparency = false;

    // Canvas für zusammengesetzte Frames
    std::vector<unsigned char> canvas(width * height, 0);

    // Backup-Buffer für Disposal=3
    std::vector<unsigned char> prevBuffer(width * height, 0);

    do {
        if (DGifGetRecordType(gif, &recordType) == GIF_ERROR)
            break;

        switch (recordType) {
        case EXTENSION_RECORD_TYPE: {
            int extCode;
            GifByteType *extension;
            if (DGifGetExtension(gif, &extCode, &extension) == GIF_ERROR)
                break;

            if (extCode == GRAPHICS_EXT_FUNC_CODE && extension != nullptr) {
                int blockSize = extension[0];
                if (blockSize >= 4) {

                    unsigned char packed = extension[1];
                    int delay_cs = extension[2] | (extension[3] << 8); // in 1/100s
                    int local_transparent = (packed & 0x01) ? extension[4] : -1;

                    disposal = (packed >> 2) & 0x07;
                    has_transparency = (packed & 0x01) != 0;
                    transparent = local_transparent;
                    delay = (delay_cs > 0) ? delay_cs * 10 : 100; // ms

//                    eDebug("Parsed GCE: disposal=%d has_trans=%d transparent=%d delay_ms=%d", disposal, has_transparency, transparent, delay);

                }

            }

            while (extension != nullptr) {
                if (DGifGetExtensionNext(gif, &extension) == GIF_ERROR)
                    break;
            }
            break;
        }

        case IMAGE_DESC_RECORD_TYPE: {
            if (DGifGetImageDesc(gif) == GIF_ERROR)
                break;

            int left   = gif->Image.Left;
            int top    = gif->Image.Top;
            int fw     = gif->Image.Width;
            int fh     = gif->Image.Height;

            // Vorherigen Frame sichern falls Disposal=3
            if (disposal == 3)
                prevBuffer = canvas;

            // Disposal anwenden
            if (disposal == 2) {
                // Hintergrund löschen (0 setzen)
                for (int y = 0; y < fh; y++) {
                    int cy = top + y;
                    if (cy >= height) continue;
                    for (int x = 0; x < fw; x++) {
                        int cx = left + x;
                        if (cx < width)
                            canvas[cy * width + cx] = 0;
                    }
                }
            }
            else if (disposal == 3) {
                canvas = prevBuffer;
            }
            // Disposal=0/1: nichts tun

            // Lokale oder globale Palette
            ColorMapObject *colorMap = gif->Image.ColorMap ? gif->Image.ColorMap : globalColorMap;

            // Frame-Daten lesen
            std::vector<unsigned char> buffer(fw * fh);
            for (int y = 0; y < fh; y++) {
                if (DGifGetLine(gif, buffer.data() + y * fw, fw) == GIF_ERROR)
                    break;
            }

            // In Canvas übertragen
            for (int y = 0; y < fh; y++) {
                int cy = top + y;
                if (cy >= height) continue;
                for (int x = 0; x < fw; x++) {
                    int cx = left + x;
                    if (cx >= width) continue;
                    unsigned char pixel = buffer[y * fw + x];
                    if (pixel == transparent)
                        continue; // Skip transparent pixel
                    canvas[cy * width + cx] = pixel;
                }
            }

            // Neues gPixmap erzeugen
            ePtr<gPixmap> pix = new gPixmap(width, height, 8, nullptr, gPixmap::accelAlways);
            unsigned char* pixdata = static_cast<unsigned char*>(pix->surface->data);

            memcpy(pixdata, canvas.data(), width * height);

            // CLUT setzen
            if (colorMap) {
                pix->surface->clut.colors = colorMap->ColorCount;
                pix->surface->clut.data = new gRGB[colorMap->ColorCount];
                for (int i = 0; i < colorMap->ColorCount; ++i) {
                    pix->surface->clut.data[i].r = colorMap->Colors[i].Red;
                    pix->surface->clut.data[i].g = colorMap->Colors[i].Green;
                    pix->surface->clut.data[i].b = colorMap->Colors[i].Blue;
                    pix->surface->clut.data[i].a = 0;  // reverse Alpha bleibt
                }
            }

            frames.push_back(pix);
            delays.push_back(delay);

            eDebug("[ePixmap] frame: %d delay=%d disposal=%d transparent=%d hasTransparency=%d left=%d top=%d w=%d h=%d", 
                (int)frames.size() - 1, delay, disposal, transparent, has_transparency,
                left, top, fw, fh);

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

    if (autostart && !m_frames.empty()) {
        m_pixmap = m_frames[0];
        event(evtChangedPixmap);
        if (m_frames.size() > 1)
            startAnimation();
    }
}

*/

void ePixmap::startAnimation(bool once)
{
    m_animTimer->stop();
    if (m_frames.size() > 1 && m_delays.size() == m_frames.size()) {
        m_animTimer->start(m_delays[m_currentFrame], true);
    }
}

void ePixmap::nextFrame()
{
    if (m_frames.empty()) return;
    
    m_currentFrame = (m_currentFrame + 1) % m_frames.size();
	m_pixmap = m_frames[m_currentFrame];
	event(evtChangedPixmap);

	if (m_currentFrame < m_delays.size())
        m_animTimer->start(m_delays[m_currentFrame], true);

}
