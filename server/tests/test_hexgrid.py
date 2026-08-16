from terrarium.world.hexgrid import axial_to_offset, hex_distance, neighbors, offset_to_axial, pixel


def test_offset_axial_roundtrip():
    for row in range(14):
        for col in range(26):
            q, r = offset_to_axial(col, row)
            assert axial_to_offset(q, r) == (col, row)


def test_distance_symmetric_neighbor():
    a = (0, 0)
    assert hex_distance(a, (1, 0)) == 1
    assert hex_distance((1, 0), a) == 1
    nbs = list(neighbors(*a))
    assert len(nbs) == 6
    assert all(hex_distance(a, n) == 1 for n in nbs)


def test_pixel_layout_spread():
    p1 = pixel(0, 0, 10.0)
    p2 = pixel(1, 0, 10.0)
    assert abs(p2[0] - p1[0] - 10 * 3 ** 0.5) < 1e-9
    assert p1[1] == p2[1]
