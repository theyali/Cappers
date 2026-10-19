def wiki_video_duration_label(video) -> str:
    if video.duration:
        return video.duration

    try:
        path = video.video.path
    except (NotImplementedError, ValueError):
        return ""

    try:
        seconds = _mp4_duration_seconds(path)
    except (OSError, IndexError, UnicodeDecodeError):
        return ""

    if not seconds:
        return ""

    total = max(0, round(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _mp4_duration_seconds(path: str) -> float | None:
    def read_atoms(file_obj, end):
        while file_obj.tell() + 8 <= end:
            start = file_obj.tell()
            header = file_obj.read(8)
            if len(header) < 8:
                return
            size = int.from_bytes(header[:4], "big")
            atom_type = header[4:8].decode("latin1")
            header_size = 8
            if size == 1:
                size = int.from_bytes(file_obj.read(8), "big")
                header_size = 16
            elif size == 0:
                size = end - start
            if size < header_size:
                return
            yield start, size, atom_type, header_size
            file_obj.seek(start + size)

    def find_atom(file_obj, end, atom_path):
        for start, size, atom_type, header_size in read_atoms(file_obj, end):
            if atom_type != atom_path[0]:
                continue
            if len(atom_path) == 1:
                return start, size, header_size
            file_obj.seek(start + header_size)
            found = find_atom(file_obj, start + size, atom_path[1:])
            if found:
                return found
        return None

    with open(path, "rb") as file_obj:
        file_obj.seek(0, 2)
        end = file_obj.tell()
        file_obj.seek(0)
        atom = find_atom(file_obj, end, ["moov", "mvhd"])
        if not atom:
            return None

        start, _, header_size = atom
        file_obj.seek(start + header_size)
        version = file_obj.read(1)[0]
        file_obj.read(3)
        if version == 1:
            file_obj.read(16)
            timescale = int.from_bytes(file_obj.read(4), "big")
            duration = int.from_bytes(file_obj.read(8), "big")
        else:
            file_obj.read(8)
            timescale = int.from_bytes(file_obj.read(4), "big")
            duration = int.from_bytes(file_obj.read(4), "big")

    return duration / timescale if timescale else None
