/*
Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License

Copyright (c) 2025 OpenATV, jbleyel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
1. Non-Commercial Use: You may not use the Software or any derivative works
   for commercial purposes without obtaining explicit permission from the
   copyright holder.
2. Share Alike: If you distribute or publicly perform the Software or any
   derivative works, you must do so under the same license terms, and you
   must make the source code of any derivative works available to the
   public.
3. Attribution: You must give appropriate credit to the original author(s)
   of the Software by including a prominent notice in your derivative works.
THE SOFTWARE IS PROVIDED "AS IS," WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES, OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE,
ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

For more details about the CC BY-NC-SA 4.0 License, please visit:
https://creativecommons.org/licenses/by-nc-sa/4.0/
*/

#ifndef __edb_h
#define __edb_h

#include <lib/base/object.h>
#include <lib/python/connections.h>


class eSocketNotifier;

class eMediaDB : public sigc::trackable
{

#ifdef SWIG
	eMediaDB();
	~eMediaDB();
#endif

public:
#ifndef SWIG
	eMediaDB();
	~eMediaDB();
#endif

	static eMediaDB *getInstance()
	{
		return m_instance;
	}

private:
	static eMediaDB *m_instance;
};

#endif
