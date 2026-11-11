# 雨衣角色素材来源

角色原画由用户在对话中提供，保存为 `assets/raincoat-reference.png`。项目中的副本与上传文件相同，SHA256 为 `0A5070AA776FA1802B3D8F70198AED767083FCDAAA7E5E78DB69D7DC6417F22E`。

显示方式由 `study_pet/raincoat.py` 实现：在绘制时排除棋盘格与独立枫叶，保留画面的笔触、高光与雨衣细节，以原图纹理组成角色各部分。原始文件不作像素修改。

本次尝试过内置图像生成工具，两次请求均在输出检查阶段被拒绝，没有产生可用的新图。成品使用用户原画，不含生成图，也没有使用CLI或API方式生成图片。

最后一次内置工具请求的提示词为：

> Use case: background-extraction. Edit target: the attached illustration of Pikachu wearing a yellow hooded raincoat. Make a clean full-body transparent cutout for use as a desktop pet. Remove the gray-and-white checkerboard background and remove the small floating orange leaf at the left. Keep the same Pikachu, same pose, face, large brown eyes, raincoat, water droplets, ears, tail, feet, warm colors and painterly illustration quality. Preserve the entire character with clean anti-aliased edges. Do not redesign it, add anything, add text or create multiple characters. The output background must be genuinely transparent alpha, with no checkerboard or solid background.
