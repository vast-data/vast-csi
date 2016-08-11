/*
 * This API is derived from the xdr streams API.
 * Our additions allow us to directly read and write from / to the underlying socket.
 *
 * Copyright (c) 2010, 2012, Oracle America, Inc.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met:
 *
 *     * Redistributions of source code must retain the above copyright
 *       notice, this list of conditions and the following disclaimer.
 *     * Redistributions in binary form must reproduce the above
 *       copyright notice, this list of conditions and the following
 *       disclaimer in the documentation and/or other materials
 *       provided with the distribution.
 *     * Neither the name of the "Oracle America, Inc." nor the names of its
 *       contributors may be used to endorse or promote products derived
 *       from this software without specific prior written permission.
 *
 *   THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 *   "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 *   LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 *   FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 *   COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
 *   INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 *   DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
 *   GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 *   INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
 *   WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
 *   NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 *   OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */


#pragma once

#include <rpc/xdr.h>

void xdrdrec_create(XDR *__xdrs, u_int __sendsize,
                    u_int __recvsize, caddr_t __tcp_handle,
                    int (*__readit) (char *, char *, int),
                    int (*__writeit) (char *, char *, int));

/* make end of xdr record */
bool_t xdrdrec_endofrecord(XDR *__xdrs, bool_t __sendnow);

/* move to beginning of next record */
bool_t xdrdrec_skiprecord(XDR *__xdrs);

/* true if no more input */
bool_t xdrdrec_eof(XDR *__xdrs);

/* Reads information directly from the XDR buffer and than from the socket, the data is not decoded. */
bool_t xdrdrec_direct_read(XDR *__xdrs, caddr_t addr, u_int len);

/* write information directly from the buffer to the the socket, the data is not encoded. */
bool_t xdrdrec_direct_write(XDR *__xdrs, caddr_t addr, u_int len, bool last);
