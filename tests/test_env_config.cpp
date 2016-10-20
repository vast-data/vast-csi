/* Copyright (C) Vast Data Ltd. */

#include <gtest/gtest.h>
#include "control/imdb/component.hpp"
#include "control/imdb/env.hpp"
#include "modules/p_module.vproto.hpp"
#include "modules/c_module.hpp"
#include "plasma/execution/env.hpp"
#include "plasma/execution/silo.hpp"

using namespace P;
using namespace Control;

namespace {

template <class ModuleObj>
static void create_module(IMDB *db, EnvObj *env, SiloId silo_id)
{
    GUID module_guid;
    module_guid.init();
    ModuleObj *module = db->create<ModuleObj>(module_guid);
    ASSERT_NOT_NULL(module);
    env->add_child(module);
    module->get_base_module()->set_silo_id(silo_id);
}

const char expected_result[] = R"(data_dir = "data";
vmsg :
{
  env_id = 123;
  port = 4567;
  local_address = "10.1.1.1";
  module_resources = (
    {
      name = "E";
      num_send_buffers = 64;
      num_recv_buffers = 64;
      num_rdma_buffers = 0;
      size_rdma_buffers = 0;
    },
    {
      name = "P";
      num_send_buffers = 64;
      num_recv_buffers = 64;
      num_rdma_buffers = 0;
      size_rdma_buffers = 0;
    },
    {
      name = "TEST";
      num_send_buffers = 64;
      num_recv_buffers = 64;
      num_rdma_buffers = 0;
      size_rdma_buffers = 0;
    },
    {
      name = "I";
      num_send_buffers = 64;
      num_recv_buffers = 64;
      num_rdma_buffers = 0;
      size_rdma_buffers = 0;
    } );
};
global_traces :
{
};
silo_types :
{
  silo_0 :
  {
    modules :
    {
      E :
      {
        components :
        {
        };
        fibers = (
          {
            count = 50;
            stack_size = 65536;
            group_id = "E";
          },
          {
            count = 1;
            stack_size = 65536;
            group_id = "E_VMSG_POLLING";
          } );
      };
      P :
      {
        components :
        {
        };
        fibers = (
          {
            count = 10;
            stack_size = 65536;
            group_id = "P";
          } );
      };
      TEST :
      {
        components :
        {
        };
        fibers = (
          {
            count = 10;
            stack_size = 65536;
            group_id = "TEST";
          } );
      };
    };
    traces :
    {
    };
  };
  silo_1 :
  {
    modules :
    {
      E :
      {
        components :
        {
        };
        fibers = (
          {
            count = 50;
            stack_size = 65536;
            group_id = "E";
          },
          {
            count = 1;
            stack_size = 65536;
            group_id = "E_VMSG_POLLING";
          } );
      };
      TEST :
      {
        components :
        {
        };
        fibers = (
          {
            count = 10;
            stack_size = 65536;
            group_id = "TEST";
          } );
      };
    };
    traces :
    {
    };
  };
  silo_2 :
  {
    modules :
    {
      E :
      {
        components :
        {
        };
        fibers = (
          {
            count = 50;
            stack_size = 65536;
            group_id = "E";
          },
          {
            count = 1;
            stack_size = 65536;
            group_id = "E_VMSG_POLLING";
          } );
      };
      I :
      {
        components :
        {
        };
        fibers = (
          {
            count = 1;
            stack_size = 65536;
            group_id = "I_NFS_POLLING";
          },
          {
            count = 16;
            stack_size = 131072;
            group_id = "I_PROTO";
          },
          {
            count = 1;
            stack_size = 65536;
            group_id = "I_IO_POLLING";
          },
          {
            count = 16;
            stack_size = 65536;
            group_id = "I_MIO";
          },
          {
            count = 16;
            stack_size = 65536;
            group_id = "I_CONTROL";
          } );
      };
    };
    traces :
    {
    };
  };
};
silos = (
  {
    type = "silo_0";
    affinity = 1;
  },
  {
    type = "silo_1";
    affinity = 2;
  },
  {
    type = "silo_2";
    affinity = -1;
  } );
nfs3 :
{
  max_read_size = 1048576;
  max_write_size = 1048576;
  nfs_port = 2049;
  mount_port = 20048;
  nlm_port = 40932;
  connections_per_silo = 256;
  requests_per_silo = 16;
};
)";

}  // namespace

static const TypeConfig TYPE_CONFIGS[] = {{TypeId::CNode, sizeof(CNode), 1},
                                          {TypeId::EnvObj, sizeof(EnvObj), 1},
                                          {TypeId::EModuleObj, sizeof(EModuleObj), 10},
                                          {TypeId::PModuleObj, sizeof(PModuleObj), 10},
                                          {TypeId::IModuleObj, sizeof(IModuleObj), 10},
                                          {TypeId::TModuleObj, sizeof(TModuleObj), 10}};

TEST(TestEnvConfig, test)
{
    IMDB db;
    db.init(NUM_ELEMENTS(TYPE_CONFIGS), TYPE_CONFIGS);

    GUID cnode_guid;
    cnode_guid.init();
    CNode *cnode = db.create<CNode>(cnode_guid);
    ASSERT_NOT_NULL(cnode);
    strcpy(cnode->get_base_node_proto()->get_addresses(0)->get_host(), "10.1.1.1");
    strcpy(cnode->get_base_node_proto()->get_addresses(1)->get_host(), "10.2.2.2");

    GUID env_guid;
    env_guid.init();
    EnvObj *env = db.create<EnvObj>(env_guid);
    ASSERT_NOT_NULL(env);
    cnode->add_child(env);
    env->set_id(123);
    env->set_port(4567);
    env->set_silo_count(3);
    env->get_silos(0)->set_affinity(1);
    env->get_silos(1)->set_affinity(2);
    env->get_silos(2)->set_affinity(-1);

    create_module<EModuleObj>(&db, env, 0);
    create_module<PModuleObj>(&db, env, 0);
    create_module<TModuleObj>(&db, env, 0);
    create_module<EModuleObj>(&db, env, 1);
    create_module<TModuleObj>(&db, env, 1);
    create_module<EModuleObj>(&db, env, 2);
    create_module<IModuleObj>(&db, env, 2);

    Env::get()->set_data_dir("/tmp");

    char config_str[P::MAX_CONFIG_SIZE];
    env->generate_config(config_str, P::MAX_CONFIG_SIZE);

    // Warning: this is ugly..
    // We remove trailing spaces from end of lines because we can't put these in our "expected_result", at least not on
    // my IDE..
    char *src = config_str;
    char *dest = config_str;
    while (*src) {
        *dest = *src;
        if (*src == ' ' && *(src + 1) == '\n') {
            src++;
            continue;
        }
        ++src; ++dest;
    }
    *dest = *src;  // '\0'

    db.destroy();

    EXPECT_STREQ(expected_result, config_str);
}

int main(int argc, char **argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
