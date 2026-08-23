import subprocess
import re

from utils.logging import get_logger

logger = get_logger('slurm_api')


# Mapping from raw SLURM status to normalized TaskStatus values
_SLURM_STATUS_MAP = {
    'COMPLETED': 'Completed',
    'PENDING': 'Pending',
    'RUNNING': 'Running',
    'CONFIGURING': 'Running',
    'COMPLETING': 'Running',
    'REQUEUED': 'Pending',
    'SUSPENDED': 'Pending',
    'CANCELLED': 'Failed',
    'FAILED': 'Failed',
    'TIMEOUT': 'Failed',
    'NODE_FAIL': 'Failed',
    'PREEMPTED': 'Failed',
    'BOOT_FAIL': 'Failed',
    'OUT_OF_MEMORY': 'Failed',
}


def normalize_slurm_status(slurm_status):
    """Map raw SLURM status string to normalized TaskStatus value.
    Returns None if input is empty/None.
    Returns 'Error' for unrecognized statuses.
    """
    if not slurm_status:
        return None
    s = slurm_status.rstrip('+').upper()
    return _SLURM_STATUS_MAP.get(s, 'Error')


def get_job_status(job_id):
    squeue_command = ["squeue", "--job", str(job_id), "--format=%T"]
    try:
        squeue_output = subprocess.check_output(squeue_command).decode("utf-8")
        lines = squeue_output.strip().split("\n")
        if len(lines) > 1:
            return lines[1].strip()
    except subprocess.CalledProcessError as e:
        logger.warning('squeue check error for job %s: %s', job_id, e)
        pass

    sacct_command = ["sacct", "--jobs",
                    str(job_id), "--format=JobID,State"]
    try:
        sacct_output = subprocess.check_output(sacct_command).decode("utf-8")
    except subprocess.CalledProcessError as e:
        logger.warning('sacct check error for job %s: %s', job_id, e)
        return None
    lines = sacct_output.strip().split("\n")
    for line in lines[1:]:
        parts = line.strip().split()
        if len(parts) == 2 and parts[0] == str(job_id):
            return parts[1]
    return None


def submit_job(shell_script, script_arguments=None, dependency_job_ids=None):


    sbatch_command = ["sbatch"]
    if dependency_job_ids is not None:
        dependencies_str = ":".join(str(job_id)
                                    for job_id in dependency_job_ids)
        sbatch_command.extend(
            ["--dependency=afterok:{}".format(dependencies_str)])
        sbatch_command.extend(["--kill-on-invalid-dep=yes"])
    sbatch_command.append(shell_script)
    if script_arguments is not None:
        sbatch_command.extend(script_arguments)
    sbatch_output = subprocess.check_output(sbatch_command).decode("utf-8")
    job_id = re.search(r"Submitted batch job (\d+)", sbatch_output).group(1)
    return job_id


def cancel_job(job_id):
    """Best-effort cancellation of a SLURM job.

    Used to clean up already-submitted prerequisite jobs when a later step of a
    task chain fails (avoids orphan jobs consuming cluster resources). Never
    raises: callers clean up regardless of whether the cancel itself succeeds.
    """
    try:
        subprocess.run(
            ["scancel", str(job_id)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except Exception as e:
        logger.warning('scancel %s error: %s', job_id, e)


