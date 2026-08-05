#define imgLoad(img, idx) imageLoad(img, ivec2((idx) & 1023, (idx) >> 10))
#define imgStore(img, idx, val) imageStore(img, ivec2((idx) & 1023, (idx) >> 10), val)

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= n_verts) return;

    int i = int(idx);
    vec4 curr = imgLoad(img_pos, i);
    vec4 old = imgLoad(img_old_pos, i);
    float mask = imgLoad(img_mask, i).r;

    if (invert_mask == 1) {
        mask = 1.0 - mask;
    }

    vec3 next = mix(curr.xyz, old.xyz, mask * factor);
    imgStore(img_pos, i, vec4(next, curr.w));
}
