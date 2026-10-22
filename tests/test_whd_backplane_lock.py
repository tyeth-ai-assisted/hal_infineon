#!/usr/bin/env python3
"""Compile the actual WHD operations with a deterministic competing bus owner."""
from pathlib import Path
import argparse,subprocess,tempfile

def functions(text,names):
 result=[]
 for name in names:
  for suffix in ('_unlocked',''):
   token='whd_result_t '+name+suffix+'('
   if token not in text:continue
   start=text.index(token)
   if text[max(0,start-7):start]=='static ':start-=7
   brace=text.index('{',start);level=1;end=brace+1
   while level:
    level+=(text[end]=='{')-(text[end]=='}');end+=1
   result.append(text[start:end])
 return '\n\n'.join(result)

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=root);parser.add_argument('--baseline',metavar='REVISION');args=parser.parse_args();root=args.root
prefix='whd-expansion/WHD/'
def source(relative):
 path=prefix+relative
 return subprocess.check_output(['git','show',args.baseline+':'+path],cwd=root,text=True) if args.baseline else (root/path).read_text()
registers=functions(source('COMPONENT_WIFI5/src/bus_protocols/whd_bus_spi_protocol.c'),['whd_bus_spi_write_backplane_value','whd_bus_spi_read_backplane_value'])
transfer=functions(source('COMMON/src/whd_bus_common.c'),['whd_bus_transfer_backplane_bytes'])
harness=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef int whd_result_t;
typedef void *whd_driver_t;
typedef void *whd_buffer_t;
typedef int whd_bus_transfer_direction_t;
typedef struct { uint32_t data[64]; } whd_transfer_bytes_packet_t;
#define WHD_SUCCESS 0
#define WHD_UNSUPPORTED -2
#define WHD_NO_REGISTER_FUNCTION_POINTER -3
#define BUS_READ 0
#define BUS_WRITE 1
#define WHD_NETWORK_RX 0
#define WHD_NETWORK_TX 1
#define BACKPLANE_FUNCTION 1
#define BACKPLANE_ADDRESS_MASK 0x7fff
#define BACKPLANE_WINDOW_SIZE 0x8000
#define SBSDIO_SB_OFT_ADDR_MASK 0x7fff
#define SBSDIO_SB_ACCESS_2_4B_FLAG 0x8000
#define CHIPCOMMON_BASE_ADDRESS 0x18000000
#define MAX_BUS_HEADER_SIZE 8
#define WHD_BACKPLAIN_BUF_TIMEOUT 0xffffffff
#define CHECK_RETURN(x) do { int r=(x); if(r) return r; } while(0)
#define CHECK_PACKET_NULL(p,e) do {if(!(p))return(e);}while(0)
#define WPRINT_WHD_ERROR(x) do{}while(0)
#define DISABLE_COMPILER_WARNING(x)
#define ENABLE_COMPILER_WARNING(x)
#define whd_mem_memcpy memcpy
static int depth,window_failure,data_failure,allocation_failure,releases,preemptions;
static uint32_t window;
static whd_transfer_bytes_packet_t packet;
static void whd_bus_lock(void){depth++;}
static void whd_bus_unlock(void){assert(depth>0);depth--;}
#define WHD_BACKPLANE_LOCK() whd_bus_lock()
#define WHD_BACKPLANE_UNLOCK() whd_bus_unlock()
/* The BT poll can run precisely after WLAN selects a window. A transaction
 * lock defers it; a lock around only the lower SPI transfer cannot do so. */
static int whd_bus_set_backplane_window(void *d,uint32_t address){
 (void)d;if(window_failure)return -10;window=address&~0x7fff;
 if(!depth){window=0x19000000;preemptions++;}return 0;
}
static int access_result(void){if(window!=CHIPCOMMON_BASE_ADDRESS)return -99;return data_failure?-11:0;}
static int whd_bus_spi_write_register_value(void*d,int f,uint32_t a,uint8_t n,uint32_t v){(void)d;(void)f;(void)a;(void)n;(void)v;return access_result();}
static int whd_bus_spi_read_register_value(void*d,int f,uint32_t a,uint8_t n,uint8_t*v){(void)d;(void)f;(void)a;(void)n;*v=42;return access_result();}
static int whd_host_buffer_get(void*d,void**p,int dir,uint16_t size,uint32_t timeout){(void)d;(void)dir;(void)size;(void)timeout;if(allocation_failure)return -12;*p=&packet;return 0;}
static void*whd_buffer_get_current_piece_data_pointer(void*d,void*p){(void)d;return p;}
static uint32_t whd_bus_get_max_transfer_size(void*d){(void)d;return 32;}
static uint32_t whd_bus_backplane_read_padd_size(void*d){(void)d;return 4;}
static int whd_bus_transfer_bytes(void*d,int dir,int f,uint32_t a,uint16_t size,whd_transfer_bytes_packet_t*p){(void)d;(void)dir;(void)f;(void)a;(void)size;(void)p;return access_result();}
static int whd_buffer_release(void*d,void*p,int dir){(void)d;(void)p;(void)dir;releases++;return 0;}
'''
main=r'''
int main(void){
 uint8_t data[64]={0};int count=0;
 for(int operation=0;operation<4;operation++){
  for(int error=0;error<4;error++){
   if(operation<2&&error==3)continue;
   for(int recursive=0;recursive<2;recursive++){
    depth=recursive;window_failure=error==1;data_failure=error==2;allocation_failure=error==3;releases=0;preemptions=0;
    int result;
    switch(operation){
     case 0:result=whd_bus_spi_read_backplane_value(NULL,CHIPCOMMON_BASE_ADDRESS+4,4,data);break;
     case 1:result=whd_bus_spi_write_backplane_value(NULL,CHIPCOMMON_BASE_ADDRESS+4,4,42);break;
     default:result=whd_bus_transfer_backplane_bytes(NULL,operation-2,CHIPCOMMON_BASE_ADDRESS+4,sizeof(data),data);break;
    }
    int expected=error==1?-10:error==2?-11:error==3?-12:0;
    if(result!=expected||depth!=recursive||preemptions){fprintf(stderr,"operation=%d error=%d recursive=%d result=%d expected=%d depth=%d competing_accesses=%d\n",operation,error,recursive,result,expected,depth,preemptions);return 1;}
    if(operation>=2)assert(releases==(error==3?0:1));
    count++;
   }
  }
 }
 printf("BACKPLANE_TRANSACTION_TEST_PASS %d cases\n",count);return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
 c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(harness+registers+'\n'+transfer+main)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Wno-unused-function','-fsanitize=undefined','-g',str(c),'-o',str(exe)],check=True)
 result=subprocess.run([str(exe)],check=False)
 if args.baseline:
  assert result.returncode!=0,'Baseline unexpectedly passed';print('BASELINE_RACE_REPRODUCED')
 else:result.check_returncode()
