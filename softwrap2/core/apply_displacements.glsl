#define imgLoad(img, idx) imageLoad(img, ivec2((idx) & 1023, (idx) >> 10))
#define imgStore(img, idx, val) imageStore(img, ivec2((idx) & 1023, (idx) >> 10), val)

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= n_verts) return;

    int i = int(idx);
    vec4 pos = imgLoad(img_pos, i);
    vec3 disp = imgLoad(img_displacements, i).xyz;
    imgStore(img_pos, i, vec4(pos.xyz + disp, pos.w));
}
