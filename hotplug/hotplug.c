#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <sys/un.h>
#include <netdb.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>


int replacechar(char *str, char orig, char rep) {
    char *ix = str;
    int n = 0;
    while((ix = strchr(ix, orig)) != NULL) {
        *ix++ = rep;
        n++;
    }
    return n;
}

int main(int argc, char *argv[])
{
	const char *action = NULL, *devpath = NULL, *physdevpath = NULL, *mediastatus = NULL;
	int sd = -1;
	struct sockaddr_un serv_addr_un;

	int mode = 0;
	int debug = 0;

	if(argc == 3)
	{
		action = argv[1];
		devpath = argv[2];
		mode = 1;
	}
	else if (argc > 3)
	{
		action = argv[1];
		devpath = argv[2];
		physdevpath = argv[3];
		if (strcmp(physdevpath, "-d") == 0)
		{
			mode = 1;
			debug = 1;
		}
		if (strcmp(physdevpath, "-e") == 0)
			mode = 2;
		if (argc > 4)
		{
			if (strcmp(argv[4], "-d") == 0)
			{
				debug = 1;
			}
		}
	}
	if (mode != 2)
	{
		memset(&serv_addr_un, 0, sizeof(serv_addr_un));
		serv_addr_un.sun_family = AF_LOCAL;
		strcpy(serv_addr_un.sun_path, "/tmp/hotplug.socket");
		sd = socket(AF_LOCAL, SOCK_STREAM, 0);
	}
	if (mode == 2 || sd >= 0)
	{
		if (mode == 2 || connect(sd, (const struct sockaddr*)&serv_addr_un, sizeof(serv_addr_un)) >= 0)
		{
			char data[1024];

			if(mode > 0)
			{
				if (action && devpath)
				{
					if (strcmp(action, "add") == 0)
					{
						if(getenv("DEVNAME"))
						{
							snprintf(data, sizeof(data) - 1, "ACTION=%s\nDEVPATH=%s\nID_TYPE=%s\nDEVTYPE=%s\nDEVNAME=%s\nID_FS_TYPE=%s\nID_BUS=%s\nID_FS_UUID=%s\nID_MODEL=%s\nID_PART_ENTRY_SIZE=%s", action, devpath , getenv("ID_TYPE") ? getenv("ID_TYPE") : "disk", getenv("DEVTYPE"), getenv("DEVNAME"), getenv("ID_FS_TYPE"), getenv("ID_BUS"), getenv("ID_FS_UUID"), getenv("ID_MODEL") ? getenv("ID_MODEL") : getenv("ID_NAME"),getenv("ID_PART_ENTRY_SIZE"));
							data[sizeof(data) - 1] = 0;
							if (debug)
								printf("%s\n", data);
							if (mode == 1)
								send(sd, data, strlen(data) + 1, 0);
							else
							{
								char devpathnorm[255];
								snprintf(devpathnorm, sizeof(devpathnorm) - 1, "%s", getenv("DEVNAME"));
								replacechar(devpathnorm, '/', '_');
								FILE *f;
								char fn[255];
								snprintf(fn, sizeof(fn) - 1, "/tmp/hotplug%s", devpathnorm);
								f = fopen(fn, "w");
								if (f)
								{
									fprintf(f, data);
									fprintf(f, "\n");
									fclose(f);
								}
							}
						}
					}
					else if(strcmp(action, "remove") == 0)
					{
						if(getenv("DEVNAME"))
						{
							snprintf(data, sizeof(data) - 1, "ACTION=%s\nDEVPATH=%s\nID_TYPE=%s\nDEVTYPE=%s\nDEVNAME=%s\nID_FS_UUID=%s", action, devpath, getenv("ID_TYPE") ? getenv("ID_TYPE") : "disk" , getenv("DEVTYPE"), getenv("DEVNAME"), getenv("ID_FS_UUID"));
							data[sizeof(data) - 1] = 0;
							if (debug)
								printf("%s\n", data);
							if (mode == 1)
								send(sd, data, strlen(data) + 1, 0);
						}
					}
					else if(strcmp(action, "ifup") == 0)
					{
						snprintf(data, sizeof(data) - 1, "ACTION=%s\nINTERFACE=%s", action, devpath);
						data[sizeof(data) - 1] = 0;
						if (debug)
							printf("%s\n", data);
						if (mode == 1)
							send(sd, data, strlen(data) + 1, 0);
					}
					else if(strcmp(action, "ifdown") == 0)
					{
						snprintf(data, sizeof(data) - 1, "ACTION=%s\nINTERFACE=%s", action, devpath);
						data[sizeof(data) - 1] = 0;
						if (debug)
							printf("%s\n", data);
						if (mode == 1)
							send(sd, data, strlen(data) + 1, 0);
					}
					else if(strcmp(action, "online") == 0)
					{
						snprintf(data, sizeof(data) - 1, "ACTION=%s\nSTATE=%s", action, devpath);
						data[sizeof(data) - 1] = 0;
						if (debug)
							printf("%s\n", data);
						if (mode == 1)
							send(sd, data, strlen(data) + 1, 0);
					}
				}
			}
			else 
			{

				if (!action) action = getenv("ACTION");
				if (action)
				{
					snprintf(data, sizeof(data) - 1, "ACTION=%s", action);
					data[sizeof(data) - 1] = 0;
					send(sd, data, strlen(data) + 1, 0);
				}
				else
				{
					mediastatus = getenv("X_E2_MEDIA_STATUS");
					if (mediastatus)
					{
						snprintf(data, sizeof(data) - 1, "X_E2_MEDIA_STATUS=%s", mediastatus);
						data[sizeof(data) - 1] = 0;
						send(sd, data, strlen(data) + 1, 0);
					}
				}

				if (!devpath)
				{
					devpath = getenv("DEVPATH");
					if (!devpath) devpath = "-";
				}
				snprintf(data, sizeof(data) - 1, "DEVPATH=%s", devpath);
				data[sizeof(data) - 1] = 0;
				send(sd, data, strlen(data) + 1, 0);
				if (!physdevpath)
				{
					physdevpath = getenv("PHYSDEVPATH");
					if (!physdevpath) physdevpath = "-";
				}
				snprintf(data, sizeof(data) - 1, "PHYSDEVPATH=%s", physdevpath);
				data[sizeof(data) - 1] = 0;
				send(sd, data, strlen(data) + 1, 0);

			}

		}
		if (mode != 2)
			close(sd);
	}
}
