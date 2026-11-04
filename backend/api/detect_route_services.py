import os
import uuid


def parse_ingest_payload(payload, normalize_detection, parse_optional_float, resolve_location, parse_int):
    if not isinstance(payload, dict):
        raise ValueError('请求体必须为 JSON 对象')

    detections_raw = payload.get('detections', [])
    if detections_raw is None:
        detections_raw = []
    if not isinstance(detections_raw, list):
        raise ValueError('detections 字段必须为数组')

    normalized_detections = []
    skipped_count = 0
    for item in detections_raw:
        normalized_item = normalize_detection(item)
        if normalized_item is None:
            skipped_count += 1
            continue
        normalized_detections.append(normalized_item)

    latitude = parse_optional_float(payload.get('latitude'))
    longitude = parse_optional_float(payload.get('longitude'))
    location = (payload.get('location') or '').strip() or resolve_location(latitude, longitude)
    device_id = (payload.get('device_id') or '').strip() or None
    source_type = (payload.get('source_type') or 'parser').strip().lower()
    source_rel_path = str(payload.get('source_path') or '').strip() or f"ingest://{uuid.uuid4().hex}"
    result_rel_path = str(payload.get('result_path') or '').strip() or None
    frame_index = parse_int(payload.get('frame_index'), 0)

    return {
        'normalized_detections': normalized_detections,
        'skipped_count': skipped_count,
        'latitude': latitude,
        'longitude': longitude,
        'location': location,
        'device_id': device_id,
        'source_type': source_type,
        'source_rel_path': source_rel_path,
        'result_rel_path': result_rel_path,
        'frame_index': frame_index,
    }


def parse_image_request(form_data, uploaded_file, parse_geo_from_form, is_allowed_image):
    latitude, longitude = parse_geo_from_form(form_data)
    device_id = (form_data.get('device_id') or '').strip() or None
    source_type = (form_data.get('source_type') or 'image').strip().lower()
    if source_type not in {'image', 'camera'}:
        source_type = 'image'

    if not uploaded_file:
        raise ValueError('未收到文件')
    if uploaded_file.filename == '' or not is_allowed_image(uploaded_file.filename):
        raise ValueError('文件类型不支持或文件名为空')

    return {
        'latitude': latitude,
        'longitude': longitude,
        'device_id': device_id,
        'source_type': source_type,
    }


def ensure_image_size_with_cleanup(source_abs_path, image_max):
    if os.path.isfile(source_abs_path) and os.path.getsize(source_abs_path) > image_max:
        os.remove(source_abs_path)
        return False
    return True


def build_image_result_paths(result_dir, file_name):
    result_abs_path = os.path.join(result_dir, file_name)
    result_rel_path = f'static/results/{file_name}'
    return result_abs_path, result_rel_path


def parse_video_request(form_data, uploaded_file, parse_geo_from_form, parse_int, is_allowed_video):
    latitude, longitude = parse_geo_from_form(form_data)
    device_id = (form_data.get('device_id') or '').strip() or None
    frame_step = max(1, parse_int(form_data.get('frame_step'), 10))
    max_frames = max(1, parse_int(form_data.get('max_frames'), 600))

    if not uploaded_file:
        raise ValueError('未收到视频文件')
    if uploaded_file.filename == '' or not is_allowed_video(uploaded_file.filename):
        raise ValueError('视频类型不支持或文件名为空')

    return {
        'latitude': latitude,
        'longitude': longitude,
        'device_id': device_id,
        'frame_step': frame_step,
        'max_frames': max_frames,
    }


def ensure_video_size_with_cleanup(source_abs_path, video_max):
    if os.path.getsize(source_abs_path) > video_max:
        os.remove(source_abs_path)
        return False
    return True
