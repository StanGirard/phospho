import concurrent.futures
from typing import Callable, Dict, Iterable, List, Literal, Optional, Union

import yaml

import phospho.lab.job_library as job_library

from .models import Any, JobResult, Message


class Job:
    job_id: str
    params: Dict[str, Any]
    job_results: Dict[str, JobResult]

    def __init__(
        self,
        job_function: Optional[Callable[..., JobResult]] = None,
        job_name: Optional[str] = None,
        job_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        """
        A job is a function that takes a message and a set of parameters and returns a result.
        It stores the result.
        """

        if params is None:
            params = {}
        self.params = params

        if job_function is None and job_name is None:
            raise ValueError("Please provide a job_function or a job_name.")

        if job_name is not None:
            # from the module .job_library import the function with the name job_name
            job_function = getattr(job_library, job_name)
        assert job_function is not None, "Please provide a job_function or a job_name."
        self.job_function = job_function

        if job_id is None:
            if job_name is not None:
                job_id = job_name
            else:
                # Make it the name of the function
                job_id = job_function.__name__

        self.job_id = job_id

        # message.id -> job_result
        self.job_results: Dict[str, JobResult] = {}

    def run(self, message: Message) -> JobResult:
        """
        Run the job on the message.
        """
        # TODO: Infer for each message its context (if any)
        # The context is the previous messages of the session

        result = self.job_function(message, **self.params)
        self.job_results[message.id] = result
        return result

    def __repr__(self):
        # Make every parameter on a new line
        concatenated_params = "\n".join(
            [f"    {k}: {v}" for k, v in self.params.items()]
        )
        return f"Job(\n  job_id={self.job_id},\n  job_name={self.job_function.__name__},\n  params={{\n{concatenated_params}\n  }}\n)"


class Workload:
    jobs: List[Job]
    results: Dict[str, Dict[str, JobResult]]

    def __init__(self):
        """
        A Workload is a set of jobs to be performed on a message.
        """
        self.jobs = []
        self.results = {}

    def add_job(self, job: Job):
        """
        Add a job to the workload.
        """
        self.jobs.append(job)

    @classmethod
    def from_config(cls, config: dict) -> "Workload":
        """
        Create a Workload from a configuration dictionary.
        """
        workload = cls()
        # Create the jobs from the configuration
        # TODO : Adds some kind of validation
        for job_id, job_config in config["jobs"].items():
            job = Job(
                job_id=job_id,
                job_name=job_config["name"],
                params=job_config.get("params", {}),
            )
            workload.add_job(job)

        return workload

    @classmethod
    def from_file(cls, config_filename: str = "phospho-config.yaml") -> "Workload":
        """
        Create a Workload from a configuration file.
        """
        with open(config_filename) as f:
            config = yaml.load(f, Loader=yaml.FullLoader)
        return cls.from_config(config)

    def run(
        self,
        messages: Iterable[Message],
        executor_type: Literal["parallel", "sequential"] = "parallel",
    ) -> Dict[str, Dict[str, JobResult]]:
        """
        Runs all the jobs on the message.

        Returns: a mapping of message.id -> job_id -> job_result
        """

        # Run the jobs sequentially on every message
        # TODO : Run the jobs in parallel on every message
        for job in self.jobs:
            if executor_type == "parallel":
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    # Submit tasks to the executor
                    # executor.map(self.evaluate_a_task, task_to_evaluate)
                    executor.map(job.run, messages)
            elif executor_type == "sequential":
                for one_message in messages:
                    job.run(one_message)
            else:
                raise NotImplementedError(
                    f"Executor type {executor_type} is not implemented"
                )

        # Collect the results:
        # Result is a mapping of message.id -> job_id -> job_result
        results: Dict[str, Dict[str, JobResult]] = {}
        for one_message in messages:
            results[one_message.id] = {}
            for job in self.jobs:
                results[one_message.id][job.job_id] = job.job_results[one_message.id]

        self.results = results
        return results

    def __repr__(self):
        concatenated_jobs = "\n".join([f"  {job}" for job in self.jobs])
        return f"Workload(jobs=[\n{concatenated_jobs}\n])"