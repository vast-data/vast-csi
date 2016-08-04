#include "net_utils.hpp"
#include <sys/socket.h>
#include <netinet/in.h>
#include <fcntl.h>

#include "plasma/utils/assert.hpp"

namespace P {
namespace Net {


void bind_socket(int fd, uint16_t port)
{
    int arg = 1;
    int ret = setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &arg, sizeof(arg));
    ASSERT_ERRNO(ret == 0);

    struct sockaddr_in sinaddr;
    memset(&sinaddr, 0, sizeof(sinaddr));
    sinaddr.sin_family = AF_INET;
    sinaddr.sin_addr.s_addr = htonl(INADDR_ANY);
    sinaddr.sin_port = htons(port);

    ret = bind(fd, (const sockaddr *)&sinaddr, sizeof(sinaddr));
    ASSERT_ERRNO(ret == 0);
    unblock_socket(fd);
}

int unblock_socket(int fd)
{
    int flags, res;

    flags = fcntl(fd, F_GETFL, 0);
    if (flags == -1) {
        perror("fcntl");
        return -1;
    }

    flags |= O_NONBLOCK;
    res = fcntl (fd, F_SETFL, flags);
    if (res == -1) {
        perror ("fcntl");
        return -1;
    }

    return 0;
}

}
}
