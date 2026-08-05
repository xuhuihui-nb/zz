#define imgLoad(img, idx) imageLoad(img, ivec2((idx) & 1023, (idx) >> 10))
#define imgStore(img, idx, val) imageStore(img, ivec2((idx) & 1023, (idx) >> 10), val)

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= n_verts) return;

    int i = int(idx);
    imgStore(img_dst, i, imgLoad(img_src, i));
}
