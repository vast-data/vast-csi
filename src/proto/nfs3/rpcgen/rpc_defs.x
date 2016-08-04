const MACHINE_NAME_LEN = 255;
const MAX_GIDS = 16;
const AUTH_SIZE = 400;

struct vauthsys_parms {
    unsigned int stamp;
    string machinename<MACHINE_NAME_LEN>;
    unsigned int uid;
    unsigned int gid;
    unsigned int gids<MAX_GIDS>;
};

enum vauth_flavor {
    VAUTH_NONE       = 0,
    VAUTH_SYS        = 1,
    VAUTH_SHORT      = 2,
    VAUTH_DH         = 3,
    VRPCSEC_GSS      = 6
};
struct vopaque_auth {
    vauth_flavor flavor;
    opaque body<AUTH_SIZE>;
};

enum vmsg_type {
    VCALL  = 0,
    VREPLY = 1
};

enum vreply_stat {
    VMSG_ACCEPTED = 0,
    VMSG_DENIED   = 1
};

enum vaccept_stat {
    VSUCCESS       = 0, /* RPC executed successfully       */
    VPROG_UNAVAIL  = 1, /* remote hasn't exported program  */
    VPROG_MISMATCH = 2, /* remote can't support version #  */
    VPROC_UNAVAIL  = 3, /* program can't support procedure */
    VGARBAGE_ARGS  = 4, /* procedure can't decode params   */
    VSYSTEM_ERR    = 5  /* e.g. memory allocation failure  */
};

enum vreject_stat {
    VRPC_MISMATCH = 0, /* RPC version number != 2          */
    VAUTH_ERROR = 1    /* remote can't authenticate caller */
};

enum vauth_stat {
    VAUTH_OK           = 0,  /* success                        */
    /*
     * failed at remote end
     */
    VAUTH_BADCRED      = 1,  /* bad credential (seal broken)   */
    VAUTH_REJECTEDCRED = 2,  /* client must begin new session  */
    VAUTH_BADVERF      = 3,  /* bad verifier (seal broken)     */
    VAUTH_REJECTEDVERF = 4,  /* verifier expired or replayed   */
    VAUTH_TOOWEAK      = 5,  /* rejected for security reasons  */
    /*
     * failed locally
     */
    VAUTH_INVALIDRESP  = 6,  /* bogus response verifier        */
    VAUTH_FAILED       = 7,  /* reason unknown                 */
    /*
     * AUTH_KERB errors; deprecated.  See [RFC2695]
     */
    VAUTH_KERB_GENERIC = 8,  /* kerberos generic error */
    VAUTH_TIMEEXPIRE = 9,    /* time of credential expired */
    VAUTH_TKT_FILE = 10,     /* problem with ticket file */
    VAUTH_DECODE = 11,       /* can't decode authenticator */
    VAUTH_NET_ADDR = 12,     /* wrong net address in ticket */
    /*
     * RPCSEC_GSS GSS related errors
     */
    VRPCSEC_GSS_CREDPROBLEM = 13, /* no credentials for user */
    VRPCSEC_GSS_CTXPROBLEM = 14   /* problem with context */
};

struct vmismatch_info {
    unsigned int low;
    unsigned int high;
};

struct vcall_body {
    unsigned int rpcvers;       /* must be equal to two (2) */
    unsigned int prog;
    unsigned int vers;
    unsigned int proc;
    vopaque_auth cred;
    vopaque_auth verf;
    /* procedure-specific parameters start here */
};

union vreply_data_body switch (vaccept_stat stat) {
case VSUCCESS:
    opaque results[0];
/*
 * procedure-specific results start here
 */
case VPROG_MISMATCH:
    vmismatch_info m_info;
default:
/*
 * Void.  Cases include PROG_UNAVAIL, PROC_UNAVAIL,
 * GARBAGE_ARGS, and SYSTEM_ERR.
 */
void;
};

struct vaccepted_reply {
    vopaque_auth verf;
    vreply_data_body reply_data;
};

union vrejected_reply switch (vreject_stat stat) {
case VRPC_MISMATCH:
    vmismatch_info m_info;
case VAUTH_ERROR:
    vauth_stat stat;
};

union vreply_body switch (vreply_stat stat) {
case VMSG_ACCEPTED:
    vaccepted_reply areply;
case VMSG_DENIED:
    vrejected_reply rreply;
};

union vrpc_msg_body switch (vmsg_type mtype) {
case VCALL:
    vcall_body cbody;
case VREPLY:
    vreply_body rbody;
};

struct vrpc_msg {
    unsigned int xid;
    vrpc_msg_body body;
};


