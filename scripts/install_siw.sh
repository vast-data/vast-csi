#!/usr/bin/env bash

rm -rf ./softiwarp

git clone https://github.com/asaf-levy/softiwarp.git
cd softiwarp

echo "index 384bfd2..2c09a53 100644
--- a/kernel/siw_debug.h
+++ b/kernel/siw_debug.h
@@ -99,7 +99,7 @@ DBG_CM|DBG_EH|DBG_MM|DBG_OBJ|DBG_TMP|DBG_DM|DBG_ON)
  * DBG_KT|DBG_ON		Kernel threads
  * DBG_ALL			All categories
  */
-#define DPRINT_MASK	0
+#define DPRINT_MASK	$1
 
 extern void siw_debug_init(void);" | patch -p1

./install_me.sh

cd ..
rm -rf ./softiwarp

sudo modprobe -r siw
sudo modprobe siw
