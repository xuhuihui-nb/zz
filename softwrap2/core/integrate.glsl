#define imgLoad(img, idx) imageLoad(img, ivec2((idx) & 1023, (idx) >> 10))
#define imgStore(img, idx, val) imageStore(img, ivec2((idx) & 1023, (idx) >> 10), val)

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= n_verts) return;

    int i = int(idx);

    // 备份当前坐标到 temp_pos
    vec4 curr_val = imgLoad(img_pos, i);
    imgStore(img_temp_pos, i, curr_val);

    vec3 curr = curr_val.xyz;
    vec3 prev = imgLoad(img_prev_pos, i).xyz;

    // Verlet 积分计算下一帧位置
    vec3 next = curr + (curr - prev) * damping;

    // 叠加控制钉位移
    next += imgLoad(img_pin_displacements, i).xyz;

    // 处理 Simulation Mask 约束
    if (use_mask == 1) {
        float mask = imgLoad(img_simulation_mask, i).r;
        if (invert_mask == 1) {
            mask = 1.0 - mask;
        }
        // 如果 mask 越接近 0，顶点越倾向于保持原位置不动，且 prev_pos 也会被重置以消除惯性
        next = mix(curr, next, mask);
        curr_val = vec4(mix(curr, curr_val.xyz, mask), curr_val.w);
    }

    // 更新位置
    imgStore(img_prev_pos, i, curr_val);
    imgStore(img_pos, i, vec4(next, curr_val.w));
}
