#!/usr/bin/env python3
"""Compile actual vendor power transitions with a competing BT wake injection."""
from pathlib import Path
import argparse,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root',type=Path,default=root)
parser.add_argument('--baseline',metavar='REVISION',help='Extract the old implementation with git show; expected to fail')
args=parser.parse_args()
relative='whd-expansion/WHD/COMPONENT_WIFI5/src/whd_chip.c'
source=(subprocess.check_output(['git','show',args.baseline+':'+relative],cwd=args.root,text=True)
        if args.baseline else (args.root/relative).read_text())

parts=[]
for name in ('whd_allow_wlan_bus_to_sleep','whd_ensure_wlan_bus_is_up'):
 for suffix in ('_unlocked',''):
  token='whd_result_t '+name+suffix+'('
  if token not in source:continue
  start=source.index(token)
  if source[max(0,start-7):start]=='static ':start-=7
  brace=source.index('{',start);end=brace+1;depth=1
  while depth:
   depth+=(source[end]=='{')-(source[end]=='}');end+=1
  parts.append(source[start:end])
harness=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
typedef int whd_result_t;
struct bt {void *bt_int_cb;};
typedef struct bt *whd_bt_dev_t;
struct driver {whd_bt_dev_t bt_dev;struct {int save_restore_enable;} chip_info;};
typedef struct driver *whd_driver_t;
#define WHD_SUCCESS 0
#define WHD_TRUE 1
#define WHD_FALSE 0
#define BACKPLANE_FUNCTION 1
#define SDIO_CHIP_CLOCK_CSR 0
#define SBSDIO_HT_AVAIL_REQ 1
#define SBSDIO_HT_AVAIL 2
#define WLAN_BUS_UP_ATTEMPTS 2
#define HT_AVAIL_WAIT_MS 1
#define WHD_BUS_UP_FAIL -12
#define WHD_SDIO_BUS_UP_FAIL -12
#define CHECK_RETURN(x) do{int r=(x);if(r)return r;}while(0)
#define WPRINT_WHD_ERROR(x) do{}while(0)
static int depth,flag,hardware,inject,competed,chip,failure;
static void whd_bus_lock(void){depth++;}
static void whd_bus_unlock(void){assert(depth>0);depth--;}
#define WHD_BACKPLANE_LOCK() whd_bus_lock()
#define WHD_BACKPLANE_UNLOCK() whd_bus_unlock()
static int whd_chip_get_chip_id(whd_driver_t d){(void)d;return chip;}
static int whd_bus_is_up(whd_driver_t d){(void)d;return flag;}
int whd_ensure_wlan_bus_is_up(whd_driver_t);
static void whd_bus_set_state(whd_driver_t d,int state){
 flag=state;
 if(!state&&!depth&&inject){
  inject=0;competed++;assert(whd_ensure_wlan_bus_is_up(d)==0);
 }
}
static int whd_bus_write_register_value(whd_driver_t d,int fn,uint32_t a,uint8_t n,uint32_t value){
 (void)d;(void)fn;(void)a;(void)n;if(failure==1)return -10;hardware=!!value;return 0;
}
static int whd_bus_read_register_value(whd_driver_t d,int fn,uint32_t a,uint8_t n,uint8_t *v){
 (void)d;(void)fn;(void)a;(void)n;if(failure==2)return -11;*v=failure==4?0:SBSDIO_HT_AVAIL;return 0;
}
static int whd_bus_sleep(whd_driver_t d){(void)d;return 0;}
static int whd_bus_wakeup(whd_driver_t d){(void)d;return 0;}
static int whd_kso_enable(whd_driver_t d,int state){(void)d;if(failure==3)return -10;hardware=state;return 0;}
static int cy_rtos_delay_milliseconds(uint32_t ms){(void)ms;return 0;}
'''
main=r'''
int main(void){struct driver d={0};int count=0;
 for(int family=0;family<2;family++)for(int sr=0;sr<2;sr++)for(int recursive=0;recursive<2;recursive++){
  chip=family?43439:43362;d.chip_info.save_restore_enable=sr;
  flag=hardware=1;inject=1;competed=0;failure=0;depth=recursive;
  assert(whd_allow_wlan_bus_to_sleep(&d)==0);
  if(flag||hardware||depth!=recursive||competed){
   fprintf(stderr,"sleep/wake race family=%d sr=%d depth=%d software_awake=%d hardware_awake=%d competing_wake=%d\n",family,sr,depth,flag,hardware,competed);return 1;
  }
  assert(whd_ensure_wlan_bus_is_up(&d)==0);
  assert(flag==1&&hardware==1&&depth==recursive);count++;
  for(int error=1;error<=4;error++){
   flag=hardware=0;inject=0;failure=error;depth=recursive;
   int result=whd_ensure_wlan_bus_is_up(&d);
   assert(depth==recursive);
   int uses_kso=family&&sr;
   if((uses_kso&&error==3)||(!uses_kso&&error!=3))assert(result!=0);
   else assert(result==0);
   count++;
  }
 }
 printf("WHD_POWER_TRANSITION_LOCK_PASS %d cases\n",count);
}
'''
with tempfile.TemporaryDirectory(prefix='envhub-power-lock-') as tmp:
 path=Path(tmp)/'test.c';path.write_text(harness+'\n'.join(parts)+main)
 binary=Path(tmp)/'test'
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Wno-unused-function','-fsanitize=undefined','-fno-sanitize-recover=all',str(path),'-o',str(binary)],check=True)
 raise SystemExit(subprocess.run([str(binary)]).returncode)
