import subprocess
import re
import sys


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
        print("squeue check error:", e, file=sys.stderr)
        pass

    sacct_command = ["sacct", "--jobs",
                    str(job_id), "--format=JobID,State"]
    try:
        sacct_output = subprocess.check_output(sacct_command).decode("utf-8")
    except subprocess.CalledProcessError as e:
        print("sacct check error:", e, file=sys.stderr)
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
    sbatch_command.append(shell_script)
    if script_arguments is not None:
        sbatch_command.extend(script_arguments)
    sbatch_output = subprocess.check_output(sbatch_command).decode("utf-8")
    job_id = re.search(r"Submitted batch job (\d+)", sbatch_output).group(1)
    return job_id


